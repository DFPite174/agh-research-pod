import hashlib
import json

import pytest

from agh_pod.cases import audit_dataset, case_status, execute_recipe


def test_published_targets_are_never_measured_without_data():
    result = execute_recipe({"recipe": "paper"})
    assert result["execution_status"] == "blocked"
    assert result["evidence_level"] == "none"
    assert result["research_status"] == "not_evaluated"
    assert all(r["observed"] is None for r in result["target_comparison"])
    assert result["published_targets"]["sample.observations"]["value"] == 14980


def test_manifest_path_escape_and_changed_file_rejected(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    manifest = private / "manifest.json"
    base = dict(source="user", license="private-authorized", snapshot_date="2026-11-03", evidence_level="alternative_vendor", sample_start="2020-01", sample_end="2022-06")
    manifest.write_text(json.dumps({**base, "files": {"../outside.jsonl": "x"}}))
    with pytest.raises(ValueError, match="path"):
        audit_dataset(manifest)
    data = private / "observations.jsonl"
    data.write_text("{}\n")
    manifest.write_text(json.dumps({**base, "files": {"observations.jsonl": hashlib.sha256(b"old").hexdigest()}}))
    with pytest.raises(ValueError, match="checksum"):
        audit_dataset(manifest)


def test_demo_is_explicit_and_never_fills_paper_targets():
    result = execute_recipe({"recipe": "demo", "paths": 1000, "steps": 80})
    assert result["evidence_level"] == "synthetic"
    assert result["research_status"] == "not_evaluated"
    assert set(result["engineering_prices"]) == {"BS", "TF", "LYW", "LW", "ZL"}
    assert all(r["observed"] is None for r in result["target_comparison"])


def test_case_has_all_core_targets_and_appendix_inventory():
    result = case_status()
    assert result["status"] == "BLOCKED"
    assert len(result["target_inventory"]) >= 21
    assert "data_gaps" in result


def test_real_recipe_executes_private_synthetic_panel_without_claiming_replication(tmp_path):
    import pandas as pd
    records = []
    for month, day in enumerate(pd.date_range("2020-01-31", periods=8, freq="ME")):
        for j in range(20):
            records.append(dict(date=str(day.date()), bond_id=f"B{j:02}", market_price=80+j*2,
                                next_return=.001*j + .0001*month*(1+j%3), risk_free=.001,
                                contract=dict(spot=8+j*.1, conversion_price=10, maturity=.1,
                                              risk_free=.03, credit_spread=.01, volatility=.2)))
    raw = "\n".join(json.dumps(r) for r in records).encode()
    (tmp_path / "observations.jsonl").write_bytes(raw)
    manifest = dict(source="synthetic-contract-test", license="CC0-synthetic", snapshot_date="2026-11-03",
                    evidence_level="synthetic", sample_start="2020-01", sample_end="2020-08",
                    files={"observations.jsonl": hashlib.sha256(raw).hexdigest()})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = execute_recipe(dict(recipe="paper", dataset=str(path), paths=50, steps=20))
    assert result["observed"]["sample.observations"] == 160
    assert result["observed"]["sample.bonds"] == 20
    assert result["evidence_level"] == "synthetic"
    assert result["research_status"] == "adaptation_only"
    assert len(result["portfolios"]) == 5
    assert not result["scientific_replication_certified"]
    assert len(result["valuations"]["ZL"]) == 160
    assert result["valuations"]["ZL"][0]["standard_error"] > 0
    import numpy as np
    f = pd.DataFrame(np.random.default_rng(9).normal(0, .02, (8, 4)), columns=["MKT", "SMB", "HML", "UMD"])
    f.insert(0, "date", pd.date_range("2020-02-29", periods=8, freq="ME").strftime("%Y-%m-%d"))
    f.to_csv(tmp_path / "factors.csv", index=False)
    manifest["files"]["factors.csv"] = hashlib.sha256((tmp_path / "factors.csv").read_bytes()).hexdigest()
    manifest["factor_models"] = {"Carhart4": ["MKT", "SMB", "HML", "UMD"]}
    path.write_text(json.dumps(manifest))
    factor_result = execute_recipe(dict(recipe="paper", dataset=str(path), paths=50, steps=20))
    assert "table3.full.BS.Carhart4" in factor_result["observed"]
    manifest["sample_start"] = "2021-01"
    manifest["sample_end"] = "2021-08"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="sample"):
        audit_dataset(path)
