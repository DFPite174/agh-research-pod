"""Frozen paper targets and recipes; measured evidence never comes from targets."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from importlib.resources import files
from pathlib import Path


def case_file(name):
    local = Path(__file__).resolve().parents[2] / "cases" / "zheng-2025" / name
    if local.is_file():
        return local
    return files("agh_pod").joinpath("case_data", "zheng-2025", name)


def _case_json(name):
    return json.loads(case_file(name).read_text(encoding="utf-8"))


def case_status():
    targets = _case_json("targets.json")
    return {
        "paper": _case_json("paper.json"),
        "status": "BLOCKED",
        "research_status": "not_evaluated",
        "published_target_count": len(targets["targets"]),
        "target_inventory": targets["inventory"],
        "data_gaps": [
            "No qualified private historical observations/contract snapshot supplied.",
            "Tushare requires credentialed coverage and entitlement probes; public docs are not acceptance.",
            "Historical clauses/reset floors and coupon/terminal total returns require event-level validation.",
            "Paper-matching treasury spot curves, one-year deposit rate and five factor-return libraries required.",
            "Author code, tie handling, adjustment vintages and appendix delta ambiguity remain unresolved.",
        ],
        "scientific_replication_certified": False,
    }


def audit_dataset(manifest_path):
    path = Path(manifest_path).resolve()
    if not path.is_file():
        raise ValueError("dataset manifest not found")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = _case_json("data-contract.json")["required_manifest_fields"]
    if not isinstance(manifest, dict) or any(not manifest.get(k) for k in required):
        raise ValueError(f"manifest requires nonempty {required}")
    if manifest["evidence_level"] not in {"synthetic", "alternative_vendor", "original_comparable"}:
        raise ValueError("unknown evidence_level")
    try:
        date.fromisoformat(manifest["snapshot_date"])
        start = date.fromisoformat(manifest["sample_start"] + "-01")
        end = date.fromisoformat(manifest["sample_end"] + "-01")
        if start > end:
            raise ValueError("reversed sample")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid manifest dates") from exc
    if not isinstance(manifest["files"], dict):
        raise ValueError("files must map relative paths to SHA256")
    checked = []
    for name, expected in manifest["files"].items():
        target = (path.parent / name).resolve()
        if not target.is_relative_to(path.parent) or target == path.parent:
            raise ValueError("dataset path escapes manifest root")
        if not target.is_file():
            raise ValueError(f"missing dataset file: {name}")
        hasher = hashlib.sha256()
        with target.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                hasher.update(block)
        actual = hasher.hexdigest()
        if actual != expected:
            raise ValueError(f"dataset checksum mismatch: {name}")
        checked.append({"name": name, "sha256": actual, "bytes": target.stat().st_size})
    if "observations.jsonl" not in manifest["files"]:
        raise ValueError("manifest must include observations.jsonl")
    nrows, bonds, months = 0, set(), set()
    with (path.parent / "observations.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            row = json.loads(line)
            needed = {"date", "bond_id", "market_price", "next_return", "risk_free", "contract"}
            if not isinstance(row, dict) or not needed.issubset(row):
                raise ValueError(f"observation {nrows+1} requires {sorted(needed)}")
            try:
                observed_date = date.fromisoformat(row["date"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"observation {nrows+1} date must be ISO calendar date") from exc
            if not start <= observed_date.replace(day=1) <= end:
                raise ValueError(f"observation {nrows+1} outside declared sample")
            if not isinstance(row["bond_id"], str) or not row["bond_id"].strip():
                raise ValueError("bond_id must be nonempty string")
            nrows += 1
            bonds.add(row["bond_id"])
            months.add(row["date"])
    if not nrows:
        raise ValueError("observations file is empty")
    return {"status": "FILES_VERIFIED_NOT_PROVIDER_QUALIFIED", "manifest": manifest,
            "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "files": checked, "observations": nrows, "bonds": len(bonds), "dates": len(months),
            "scientific_replication_certified": False}


def _comparison(observed=None, blocked=False):
    from .empirical import compare_targets
    targets = _case_json("targets.json")["targets"]
    if blocked:
        observed = {key: {"status": "BLOCKED", "reason": "qualified original-comparable data absent"} for key in targets}
    frame = compare_targets(targets, observed)
    # pandas promotes absent numeric values to NaN; strict JSON must use null.
    return json.loads(frame.to_json(orient="records"))


def execute_recipe(payload):
    from .pricing import BondContract, price
    if payload["recipe"] == "demo":
        contract = BondContract(spot=10, conversion_price=10, maturity=1, risk_free=.03,
                                credit_spread=0, volatility=.25)
        prices = {m: price(contract, m, steps=payload.get("steps", 200),
                           paths=payload.get("paths", 10000), seed=payload.get("seed", 42))
                  for m in ("BS", "TF", "LYW", "LW", "ZL")}
        return {"execution_status": "succeeded", "evidence_level": "synthetic",
                "research_status": "not_evaluated", "label": "ENGINEERING DEMO — NO MARKET RETURNS",
                "engineering_prices": prices, "target_comparison": _comparison(),
                "scientific_replication_certified": False}
    if payload["recipe"] != "paper":
        raise ValueError("unknown trusted recipe")
    if not payload.get("dataset"):
        return {"execution_status": "blocked", "evidence_level": "none", "research_status": "not_evaluated",
                "published_targets": _case_json("targets.json")["targets"],
                "target_comparison": _comparison(blocked=True), "readiness": case_status(),
                "observed": {}, "scientific_replication_certified": False}
    return _run_panel(payload)


def _run_panel(payload):
    import numpy as np
    import pandas as pd
    from .empirical import factor_alpha, form_portfolios, hac_mean, table1_statistics
    from .pricing import contract_from_dict, price

    audit = audit_dataset(payload["dataset"])
    manifest_path = Path(payload["dataset"]).resolve()
    rows = [json.loads(line) for line in (manifest_path.parent / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    observed = {"sample.bonds": audit["bonds"], "sample.observations": audit["observations"]}
    all_prices, valuations, portfolios, holding_portfolios, statistics, missing, errors = {}, {}, {}, {}, {}, [], []
    # Freeze file bytes via checksum before and after; detected mutations invalidate the run.
    for model in ("BS", "TF", "LYW", "LW", "ZL"):
        model_rows, values, records = [], [], []
        for i, row in enumerate(rows):
            result = price(contract_from_dict(row["contract"]), model, steps=payload.get("steps", 200),
                           paths=payload.get("paths", 10000), seed=(payload.get("seed", 42) + i) % 2**32)
            values.append(result["price"])
            records.append({"date": row["date"], "bond_id": row["bond_id"], **result})
            model_rows.append({"date": row["date"], "bond_id": row["bond_id"],
                               "market_price": row["market_price"], "model_price": result["price"],
                               "next_return": row["next_return"], "risk_free": row["risk_free"]})
        all_prices[model] = values
        valuations[model] = records
        if len(values) >= 2:
            stats = table1_statistics(pd.DataFrame({model: values})).loc[model].to_dict()
            for key in ("nobs", "mean", "std", "min", "median", "max"):
                observed[f"table1.{model}.{key}"] = stats[key]
        grouped = form_portfolios(pd.DataFrame(model_rows))
        if grouped.empty:
            missing.append(f"{model}: no formation month meets minimum bond count")
            continue
        memberships = grouped.attrs.get("membership", [])
        portfolios[model] = {"rows": json.loads(grouped.to_json(orient="records", date_format="iso")),
                             "method": str(grouped.attrs.get("conventions", "see empirical-methods.md")),
                             "membership_count": len(memberships),
                             "excluded_months": str(grouped.attrs.get("excluded_months", []))}
        holding_dates = (pd.DatetimeIndex(grouped.date).to_period("M") + 1).to_timestamp("M")
        grouped = grouped.set_index(holding_dates)
        holding_portfolios[model] = grouped
        for panel, sample in {"full": grouped, "pre2018": grouped[grouped.index < "2018-01-01"],
                              "post2018": grouped[grouped.index >= "2018-01-01"]}.items():
            if len(sample) < 6:
                missing.append(f"{model}/{panel}: fewer than6 holding months; HAC inference not evaluated")
                continue
            for metric, column in [(f"q{k}", f"q{k}_excess") for k in range(1, 6)] + [("low_minus_high", "low_minus_high")]:
                try:
                    summary = hac_mean(sample[column])
                    statistics[f"{model}.{panel}.{metric}"] = summary
                    observed[f"table2.{panel}.{model}.{metric}"] = summary["estimate"]
                    if summary["t_stat"] is not None:
                        observed[f"table2.{panel}.{model}.{metric}.t"] = summary["t_stat"]
                except ValueError as exc:
                    errors.append(f"{model}/{panel}/{metric}: {exc}")
            try:
                alpha = factor_alpha(sample.low_minus_high, pd.DataFrame({"MKT": sample.market_excess}, index=sample.index))
                observed[f"table2.{panel}.{model}.MKT_alpha"] = alpha["alpha"]
                if alpha["t_stat"] is not None:
                    observed[f"table2.{panel}.{model}.MKT_alpha.t"] = alpha["t_stat"]
            except ValueError as exc:
                errors.append(f"{model}/{panel}/MKT: {exc}")
    if "factors.csv" in audit["manifest"]["files"]:
        from .factor_evaluation import evaluate_factor_models
        factors = pd.read_csv(manifest_path.parent / "factors.csv")
        if "date" not in factors:
            raise ValueError("factors.csv requires holding-month date")
        factors.index = pd.DatetimeIndex(pd.to_datetime(factors.pop("date")))
        evaluation = evaluate_factor_models(holding_portfolios, factors, audit["manifest"].get("factor_models", {}))
        observed.update(evaluation["observed"])
        statistics.update(evaluation["statistics"])
        errors.extend(evaluation["errors"])
    else:
        missing.append("Table3 external factor series not supplied to this recipe.")
    final_audit = audit_dataset(payload["dataset"])
    if audit["manifest_sha256"] != final_audit["manifest_sha256"]:
        raise ValueError("dataset manifest changed during run")
    missing += ["Figures and appendix robustness require separately approved recipes; inventoried, not certified.",
                "Model/clause assumptions are disclosed approximations; author implementation unavailable."]
    if not np.isfinite(np.array(list(all_prices.values()), dtype=float)).all():
        raise ValueError("nonfinite model output")
    return {"execution_status": "succeeded", "evidence_level": audit["manifest"]["evidence_level"],
            "research_status": "adaptation_only" if audit["manifest"]["evidence_level"] != "original_comparable" else "inconclusive",
            "audit": audit, "observed": observed, "target_comparison": _comparison(observed),
            "model_prices": all_prices, "valuations": valuations, "portfolios": portfolios, "statistics": statistics,
            "unevaluated": missing, "inference_errors": errors, "scientific_replication_certified": False}
