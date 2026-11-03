import json
from pathlib import Path

import pytest

from agh_pod.workflow import Pod, StateError, IntegrityError


def test_unapproved_run_refused_and_approved_spec_immutable(tmp_path):
    pod = Pod(tmp_path)
    opportunity = pod.create_opportunity("first", "investment_research")
    spec = pod.create_spec(opportunity["id"], {"recipe": "demo", "seed": 7})
    with pytest.raises(StateError, match="approved"):
        pod.run_spec(spec["id"])
    pod.approve(spec["id"])
    run = pod.run_spec(spec["id"], idempotency_key="same")
    assert run["status"] == "succeeded"
    assert run["evidence_level"] == "synthetic"
    assert pod.run_spec(spec["id"], idempotency_key="same")["id"] == run["id"]
    with pytest.raises(StateError):
        pod.approve(spec["id"])
    assert pod.get("spec", spec["id"])["payload"] == {"recipe": "demo", "seed": 7}


def test_paper_missing_dataset_blocked_without_fabricated_values(tmp_path):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("paper", "investment_research")
    spec = pod.create_spec(op["id"], {"recipe": "paper", "dataset": None})
    pod.approve(spec["id"])
    run = pod.run_spec(spec["id"])
    assert run["status"] == "blocked"
    assert run["research_status"] == "not_evaluated"
    assert not run["result"].get("observed")


def test_artifact_tamper_and_export_checksum_detected(tmp_path):
    pod = Pod(tmp_path)
    a = pod.add_artifact("manual", "paper", b"evidence", {"page": 3})
    assert pod.read_artifact(a["id"]) == b"evidence"
    Path(a["path"]).write_bytes(b"changed")
    with pytest.raises(IntegrityError):
        pod.read_artifact(a["id"])


def test_review_required_and_package_verification(tmp_path):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("demo", "capability_evaluation")
    spec = pod.create_spec(op["id"], {"recipe": "demo"})
    pod.approve(spec["id"])
    run = pod.run_spec(spec["id"])
    with pytest.raises(StateError, match="review"):
        pod.export_package(run["id"])
    pod.review(run["id"], "local-engineering-review", "engineering_verified")
    package = pod.export_package(run["id"])
    assert pod.verify_package(package["path"])["valid"]
    root = Path(package["path"])
    (root / "run.json").write_text("{}")
    assert not pod.verify_package(root)["valid"]


def test_no_unknown_recipe_execution_and_no_idempotency_collision(tmp_path):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("demo", "investment_research")
    with pytest.raises(ValueError, match="recipe"):
        pod.create_spec(op["id"], {"recipe": "shell", "command": "danger"})
    one = pod.create_spec(op["id"], {"recipe": "demo", "seed": 1})
    two = pod.create_spec(op["id"], {"recipe": "demo", "seed": 2})
    pod.approve(one["id"])
    pod.approve(two["id"])
    pod.run_spec(one["id"], idempotency_key="unique")
    with pytest.raises(StateError, match="conflict"):
        pod.run_spec(two["id"], idempotency_key="unique")


def test_package_manifest_path_escape_refused(tmp_path):
    p = tmp_path / "package"
    p.mkdir()
    (p / "manifest.json").write_text(json.dumps({"files": {"../secret": "x"}}))
    with pytest.raises(IntegrityError, match="path"):
        Pod.verify_package(p)


def test_checksum_only_empty_json_is_not_a_valid_research_package(tmp_path):
    from agh_pod.workflow import canonical, digest
    p = tmp_path / "empty"
    p.mkdir()
    values = {"run.json": {}, "spec.json": {}, "opportunity.json": {}, "reviews.json": []}
    for name, value in values.items():
        (p / name).write_bytes(canonical(value))
    (p / "manifest.json").write_bytes(canonical({"schema_version": 1, "files": {name: digest((p / name).read_bytes()) for name in values}}))
    assert not Pod.verify_package(p)["valid"]


def test_recover_does_not_skip_old_running_jobs(tmp_path):
    pod = Pod(tmp_path)
    run = pod._new("run", status="running")
    for _ in range(1001):
        pod._new("run", status="succeeded")
    assert run["id"] in pod.recover()


def test_approval_binds_manifest_bytes(tmp_path):
    data = tmp_path / "manifest.json"
    data.write_text('{"one":1}')
    pod = Pod(tmp_path / "pod")
    op = pod.create_opportunity("paper", "investment_research")
    spec = pod.create_spec(op["id"], {"recipe": "paper", "dataset": str(data)})
    pod.approve(spec["id"])
    data.write_text('{"one":2}')
    run = pod.run_spec(spec["id"])
    assert run["status"] == "failed"
    assert run["error_type"] == "IntegrityError"


def test_evidence_is_linked_and_frozen_into_spec_and_package(tmp_path):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("source-backed", "capability_evaluation")
    artifact = pod.add_artifact("manual", "source", b"supporting evidence")
    pod.link_artifact(op["id"], artifact["id"])
    spec = pod.create_spec(op["id"], {"recipe": "demo"})
    assert spec["evidence"][0]["sha256"] == artifact["sha256"]
    pod.approve(spec["id"])
    run = pod.run_spec(spec["id"])
    pod.review(run["id"], "review", "engineering_verified")
    pkg = pod.export_package(run["id"])
    assert json.loads((Path(pkg["path"]) / "spec.json").read_text())["evidence"][0]["id"] == artifact["id"]
