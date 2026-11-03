"""Local interfaces exercise the real evidence store and trusted recipes."""
import importlib
import json

import pytest

from agh_pod.workflow import Pod


def client(root):
    assert importlib.util.find_spec("agh_pod.api") is not None, "API implementation missing"
    from fastapi.testclient import TestClient
    from agh_pod.api import create_app
    return TestClient(create_app(root))


def cli():
    assert importlib.util.find_spec("agh_pod.cli") is not None, "CLI implementation missing"
    return importlib.import_module("agh_pod.cli")


def opportunity(c, title="Synthetic research"):
    response = c.post("/v1/opportunities", json={"title": title, "research_type": "capability_evaluation"})
    assert response.status_code == 201
    return response.json()


def spec(c, op):
    response = c.post(f"/v1/opportunities/{op['id']}/specs", json={"recipe": "demo", "seed": 7})
    assert response.status_code == 201
    return response.json()


def test_health_and_persisted_opportunity_listing(tmp_path):
    c = client(tmp_path)
    assert c.get("/v1/health").json()["status"] == "ok"
    op = opportunity(c)
    assert c.get("/v1/opportunities").json()[0]["id"] == op["id"]
    assert client(tmp_path).get("/v1/opportunities").json()[0]["id"] == op["id"]
    assert c.get("/v1/artifacts").json() == []


def test_full_api_approval_run_review_package_and_idempotency(tmp_path):
    c = client(tmp_path)
    s = spec(c, opportunity(c))
    assert c.post(f"/v1/specs/{s['id']}/runs", json={}).status_code == 409
    assert c.post(f"/v1/specs/{s['id']}/approve", json={}).status_code == 200
    response = c.post(f"/v1/specs/{s['id']}/runs", json={}, headers={"Idempotency-Key": "once"})
    assert response.status_code == 202
    run_id = response.json()["id"]
    run = c.get(f"/v1/runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert run["evidence_level"] == "synthetic"
    again = c.post(f"/v1/specs/{s['id']}/runs", json={}, headers={"Idempotency-Key": "once"})
    assert again.json()["id"] == run_id
    assert len(Pod(tmp_path).list("run")) == 1
    another = spec(c, opportunity(c, "another approved specification"))
    c.post(f"/v1/specs/{another['id']}/approve", json={})
    assert c.post(f"/v1/specs/{another['id']}/runs", json={}, headers={"Idempotency-Key": "once"}).status_code == 409
    assert c.post(f"/v1/runs/{run_id}/packages", json={}).status_code == 409
    review = c.post(f"/v1/runs/{run_id}/reviews", json={"reviewer": "local reviewer", "decision": "engineering_verified"})
    assert review.status_code == 201
    package = c.post(f"/v1/runs/{run_id}/packages", json={})
    assert package.status_code == 201
    assert Pod.verify_package(package.json()["path"])["valid"]
    assert c.post(f"/v1/runs/{run_id}/cancel", json={}).status_code == 409


def test_cancel_queued_job_and_missing_ids_have_correct_errors(tmp_path):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("queued", "investment_research")
    s = pod.create_spec(op["id"], {"recipe": "demo"})
    pod.approve(s["id"])
    run = pod.submit(s["id"])
    c = client(tmp_path)
    assert c.post(f"/v1/runs/{run['id']}/cancel", json={}).json()["status"] == "cancelled"
    assert c.get("/v1/runs/missing").status_code == 404
    assert c.post("/v1/specs/missing/approve", json={}).status_code == 404
    assert c.post("/v1/opportunities/missing/specs", json={"recipe": "demo"}).status_code == 404


@pytest.mark.parametrize("body", [
    {"title": "x", "research_type": "investment_research", "command": "bad"},
    {"title": "x", "research_type": "invalid"},
    {"title": "", "research_type": "investment_research"},
    {"title": 7, "research_type": "investment_research"},
])
def test_strict_opportunity_schema_rejects_unknown_fields_and_types(tmp_path, body):
    assert client(tmp_path).post("/v1/opportunities", json=body).status_code == 422


def test_strict_recipe_and_action_bodies_refuse_shell_and_unknown_fields(tmp_path):
    c = client(tmp_path)
    op = opportunity(c)
    path = f"/v1/opportunities/{op['id']}/specs"
    for body in [{"recipe": "shell"}, {"recipe": "demo", "command": "bad"},
                 {"recipe": "demo", "seed": True}, {"recipe": "demo", "paths": 1}]:
        assert c.post(path, json=body).status_code == 422
    s = spec(c, op)
    assert c.post(f"/v1/specs/{s['id']}/approve", json={"ignore": True}).status_code == 422
    assert c.get("/v1/artifacts?limit=1001").status_code == 422
    assert c.get("/v1/files?path=../../secret").status_code == 404


def test_main_ui_escapes_external_titles_and_has_actionable_forms(tmp_path):
    c = client(tmp_path)
    opportunity(c, "<script>alert('xss')</script>")
    Pod(tmp_path).add_artifact("manual", "<img src=x onerror=alert(1)>", b"evidence")
    page = c.get("/")
    assert page.status_code == 200
    assert "<script>alert('xss')</script>" not in page.text
    assert "&lt;script&gt;" in page.text
    assert "&lt;img" in page.text
    assert 'id="opportunity-form"' in page.text
    assert 'id="spec-form"' in page.text
    assert "textContent" in page.text
    assert "innerHTML" not in page.text


def test_api_links_existing_artifact_to_opportunity_and_rejects_unknown_ids(tmp_path):
    c = client(tmp_path)
    op = opportunity(c)
    a = Pod(tmp_path).add_artifact("manual", "Source", b"source evidence")
    route = f"/v1/opportunities/{op['id']}/artifacts"
    response = c.post(route, json={"artifact_id": a["id"]})
    assert response.status_code == 200
    assert a["id"] in Pod(tmp_path).get("opportunity", op["id"])["artifacts"]
    assert c.post(route, json={"artifact_id": "missing"}).status_code == 404
    assert c.post(route, json={"artifact_id": a["id"], "path": "../secret"}).status_code == 422


def test_cli_demo_creates_reviewed_synthetic_package(tmp_path, capsys):
    assert cli().main(["--root", str(tmp_path), "demo"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["run"]["evidence_level"] == "synthetic"
    assert result["verification"]["valid"]
    assert result["scientific_replication_certified"] is False


def test_cli_import_listing_and_missing_path_errors(tmp_path, capsys):
    path = tmp_path / "note.txt"
    path.write_text("local source evidence", encoding="utf-8")
    root = tmp_path / "pod"
    assert cli().main(["--root", str(root), "import", str(path), "--title", "A note"]) == 0
    artifact = json.loads(capsys.readouterr().out)
    assert artifact["title"] == "A note"
    assert cli().main(["--root", str(root), "list", "artifact"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == artifact["id"]
    assert cli().main(["--root", str(root), "import", str(tmp_path / "missing.txt")]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_cli_doctor_never_outputs_credential_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "private-do-not-print")
    monkeypatch.setenv("AGH_LLM_API_KEY", "agh-private-do-not-print")
    assert cli().main(["--root", str(tmp_path), "doctor"]) == 0
    text = capsys.readouterr().out
    assert "private-do-not-print" not in text
    result = json.loads(text)
    assert result["credentials"]["OPENAI_API_KEY"] is True
    assert result["credentials"]["AGH_LLM_API_KEY"] is True
    assert result["docker"]["status"] in {"AVAILABLE", "BLOCKED"}


def test_cli_worker_once_executes_queued_real_pod_job(tmp_path, capsys):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("worker", "capability_evaluation")
    s = pod.create_spec(op["id"], {"recipe": "demo", "seed": 7})
    pod.approve(s["id"])
    run = pod.submit(s["id"])
    assert cli().main(["--root", str(tmp_path), "worker", "--once"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["runs"][0]["id"] == run["id"]
    assert pod.get("run", run["id"])["status"] == "succeeded"


def test_cli_recover_requires_explicit_stopped_worker_assertion(tmp_path, capsys):
    assert cli().main(["--root", str(tmp_path), "recover"]) == 2
    assert "stopped" in json.loads(capsys.readouterr().err)["error"]


def test_cli_worker_reports_failure_exit_code_for_tampered_queued_spec(tmp_path, capsys):
    pod = Pod(tmp_path)
    op = pod.create_opportunity("tampering negative test", "capability_evaluation")
    s = pod.create_spec(op["id"], {"recipe": "demo", "seed": 7})
    pod.approve(s["id"])
    run = pod.submit(s["id"])
    damaged = pod.get("spec", s["id"])
    damaged["payload"]["seed"] = 8
    pod._save("spec", damaged)  # Deliberate durable-store corruption, not a mocked workflow.
    assert cli().main(["--root", str(tmp_path), "worker", "--once"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["runs"][0]["status"] == "failed"
    assert pod.get("run", run["id"])["error_type"] == "IntegrityError"


def test_cli_case_run_retries_same_request_without_creating_another_spec(tmp_path, capsys):
    # Invalid supplied manifest produces a failed recipe; idempotence retains failures too.
    root = tmp_path / "pod"
    path = tmp_path / "invalid-manifest.json"
    path.write_text("{}", encoding="utf-8")
    args = ["--root", str(root), "case-run", "--manifest", str(path), "--idempotency-key", "paper-once"]
    assert cli().main(args) == 1
    first = json.loads(capsys.readouterr().out)
    assert cli().main(args) == 1
    second = json.loads(capsys.readouterr().out)
    assert second["id"] == first["id"]
    assert len(Pod(root).list("spec")) == 1
    assert len(Pod(root).list("opportunity")) == 1
    other = ["--root", str(root), "case-run", "--manifest", str(tmp_path / "different.json"),
             "--idempotency-key", "paper-once"]
    assert cli().main(other) == 2
    assert "conflict" in json.loads(capsys.readouterr().err)["error"]
    assert len(Pod(root).list("spec")) == 1


def test_cli_worker_finds_old_queued_job_behind_over_1000_terminal_records(tmp_path, capsys):
    import sqlite3
    pod = Pod(tmp_path)
    op = pod.create_opportunity("old queued job", "capability_evaluation")
    s = pod.create_spec(op["id"], {"recipe": "demo", "seed": 7})
    pod.approve(s["id"])
    run = pod.submit(s["id"])
    # Seed terminal history in one transaction; executing 1001 demos is not needed.
    with sqlite3.connect(pod.db) as connection:
        connection.executemany("INSERT INTO objects(kind,id,body) VALUES (?,?,?)", [
            ("run", f"terminal-{i}", json.dumps({"id": f"terminal-{i}", "status": "cancelled"}))
            for i in range(1001)
        ])
    assert cli().main(["--root", str(tmp_path), "worker", "--once"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in result["runs"]] == [run["id"]]
    assert pod.get("run", run["id"])["status"] == "succeeded"


def test_cli_price_uses_real_contract_parser_and_rejects_unknown_terms(tmp_path, capsys):
    path = tmp_path / "contract.json"
    contract = dict(spot=8, conversion_price=10, maturity=0, risk_free=.02,
                    credit_spread=0, volatility=.2)
    path.write_text(json.dumps(contract), encoding="utf-8")
    assert cli().main(["price", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["price"] == pytest.approx(100)
    contract["unknown_term"] = True
    path.write_text(json.dumps(contract), encoding="utf-8")
    assert cli().main(["price", str(path)]) == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_cli_missing_credentials_are_not_run_without_network(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("AGH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AGH_LLM_MODEL", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    pod = Pod(tmp_path)
    a = pod.add_artifact("manual", "Research evidence", b"Finite source content")
    assert cli().main(["--root", str(tmp_path), "analyze", a["id"]]) == 0
    analysis = json.loads(capsys.readouterr().out)
    assert analysis["status"] == "NOT_RUN"
    assert cli().main(["--root", str(tmp_path), "tushare-probe"]) == 0
    probe = json.loads(capsys.readouterr().out)
    assert probe["status"] == "NOT_RUN"


def test_cli_lake_audit_and_backend_probe_have_explicit_interfaces(tmp_path, capsys):
    assert cli().main(["lake-audit", "--database", str(tmp_path / "missing.duckdb")]) == 2
    assert "error" in json.loads(capsys.readouterr().err)
    assert cli().main(["engine-probe", "--engine-root", str(tmp_path / "missing-engine")]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"


def test_ui_repeated_submission_reuses_same_spec_idempotency_key():
    """Execute the shipped form handler; no source-string equality assertion."""
    from pathlib import Path
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("optional Node check; browser acceptance must cover repeated submissions")
    template = Path(__file__).parents[1] / "src" / "agh_pod" / "templates" / "index.html"
    script = re.findall(r"<script>(.*?)</script>", template.read_text(encoding="utf-8"), re.S)[0]
    harness = r"""
const elements={};const requests=[];let randomCalls=0;
globalThis.crypto={randomUUID:()=>String(++randomCalls)};
globalThis.document={getElementById:(id)=>elements[id]??=(
  {data:{},addEventListener(name,handler){this.handler=handler},
   querySelector(){return {disabled:false}},scrollIntoView(){}})};
globalThis.location={reload(){}};
globalThis.FormData=class{constructor(form){this.form=form}*[Symbol.iterator](){yield* Object.entries(this.form.data)}};
globalThis.fetch=async(path,options)=>{requests.push({path,key:options.headers['Idempotency-Key']});return {status:202,json:async()=>({id:'run'})}};
"""
    actions = r"""
const form=elements['run-form'];
for(const id of ['spec-A','spec-A','spec-B']){form.data={spec_id:id};form.handler({preventDefault(){},currentTarget:form});}
setImmediate(()=>process.stdout.write(JSON.stringify(requests)));
"""
    completed = subprocess.run([node, "-"], input=harness+script+actions, text=True,
                               capture_output=True, check=True, timeout=10)
    requests = json.loads(completed.stdout)
    assert requests[0]["key"] == requests[1]["key"] == "ui:spec-A"
    assert requests[2]["key"] == "ui:spec-B"
