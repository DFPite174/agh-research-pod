"""Argparse CLI; only built-in recipes execute, through the same Pod as HTTP."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .workflow import Pod, StateError


def _print(value, *, error=False):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), file=sys.stderr if error else sys.stdout)


def doctor():
    """Check executable AND daemon; report only credential names and existence."""
    docker = {"status": "BLOCKED", "reason": "Docker executable unavailable"}
    executable = shutil.which("docker")
    if executable:
        try:
            probe = subprocess.run([executable, "info", "--format", "{{.ServerVersion}}"],
                                   capture_output=True, text=True, timeout=8, check=False,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            docker = ({"status": "AVAILABLE", "server_version": probe.stdout.strip()}
                      if probe.returncode == 0 and probe.stdout.strip()
                      else {"status": "BLOCKED", "reason": "Docker daemon not reachable"})
        except (OSError, subprocess.TimeoutExpired):
            docker = {"status": "BLOCKED", "reason": "Docker daemon probe failed or timed out"}
    names = ["AGH_LLM_API_KEY", "AGH_LLM_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
             "GITHUB_TOKEN", "HF_TOKEN", "TUSHARE_TOKEN"]
    return {"docker": docker, "credentials": {name: bool(os.environ.get(name)) for name in names},
            "untrusted_execution": "NOT_RUN; only a separately approved Docker route may execute external code",
            "scope": "local single trusted user; no scientific replication certification"}


def _parser():
    parser = argparse.ArgumentParser(prog="agh", description="AGH evidence research workbench")
    parser.add_argument("--root", default="./runtime", help="local Pod storage directory (before subcommand)")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="serve the local workbench on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    commands.add_parser("doctor")
    commands.add_parser("demo", help="run reviewed built-in SYNTHETIC demonstration")
    commands.add_parser("case-status")
    commands.add_parser("tushare-probe", help="explicit small entitlement probes; no token means NOT_RUN")
    lake = commands.add_parser("lake-audit", help="read-only audit of the explicitly supplied DuckDB")
    lake.add_argument("--database", default=os.getenv("AGH_DATA_LAKE_PATH"))
    engine = commands.add_parser("engine-probe", help="probe the pinned user-selected NT backtest engine")
    engine.add_argument("--engine-root", default=os.getenv("AGH_BACKTEST_ENGINE_ROOT"))
    engine.add_argument("--python", default=os.getenv("AGH_ENGINE_PYTHON"))
    analysis = commands.add_parser("analyze", help="analyze hash-checked evidence with configured bounded model")
    analysis.add_argument("artifact_ids", nargs="+")
    analysis.add_argument("--max-total-tokens", type=int, default=5000)
    analysis.add_argument("--max-output-tokens", type=int, default=1200)
    source = commands.add_parser("source-sync")
    source.add_argument("source", choices=["arxiv", "github", "huggingface-model", "huggingface-dataset"])
    source.add_argument("reference")
    local = commands.add_parser("import", help="import local PDF/text bytes as evidence; never execute")
    local.add_argument("path")
    local.add_argument("--title")
    listing = commands.add_parser("list")
    listing.add_argument("kind", choices=["opportunity", "artifact", "spec", "run", "review", "package", "delivery", "analysis", "research", "research_attempt", "research_package"])
    listing.add_argument("--limit", type=int, default=200)
    listing.add_argument("--offset", type=int, default=0)
    approve = commands.add_parser("approve")
    approve.add_argument("spec_id")
    run = commands.add_parser("run")
    run.add_argument("spec_id")
    run.add_argument("--idempotency-key")
    worker = commands.add_parser("worker", help="execute queued work in one finite sweep")
    worker.add_argument("--once", action="store_true", required=True)
    package = commands.add_parser("package-verify")
    package.add_argument("path")
    recover = commands.add_parser("recover", help="mark abandoned running jobs interrupted after workers stop")
    recover.add_argument("--workers-stopped", action="store_true")
    pricing = commands.add_parser("price", help="price a contract JSON object")
    pricing.add_argument("path")
    pricing.add_argument("--model", choices=["BS", "TF", "LYW", "LW", "ZL"], default="BS")
    pricing.add_argument("--steps", type=int, default=200)
    pricing.add_argument("--paths", type=int, default=10000)
    pricing.add_argument("--seed", type=int, default=42)
    for name in ("data-audit", "case-run"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", required=True)
        if name == "case-run":
            command.add_argument("--idempotency-key")
    quant = commands.add_parser("quant-run", help="execute an explicitly authorized frozen quant task JSON")
    quant.add_argument("task")
    review = commands.add_parser("review")
    review.add_argument("run_id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--decision", required=True)
    package = commands.add_parser("package")
    package.add_argument("run_id")
    receive = commands.add_parser("receive")
    receive.add_argument("package_id")
    receive.add_argument("--receiver", required=True)
    receive.add_argument("--decision", choices=["accepted", "rejected", "followup"], required=True)
    receive.add_argument("--reason", required=True)
    research = commands.add_parser("research-start", help="manually trigger AI research with selected NT engine")
    research.add_argument("task")
    research.add_argument("--engine-root", default=os.getenv("AGH_BACKTEST_ENGINE_ROOT"))
    research.add_argument("--engine-python", default=os.getenv("AGH_ENGINE_PYTHON"))
    export = commands.add_parser("research-export")
    export.add_argument("task_id")
    return parser


def _demo(pod):
    op = pod.create_opportunity("Synthetic software demonstration", "capability_evaluation",
                                "Engineering arithmetic only; no market-performance claim")
    spec = pod.create_spec(op["id"], {"recipe": "demo", "seed": 7})
    pod.approve(spec["id"])
    run = pod.run_spec(spec["id"])
    if run["status"] != "succeeded":
        return {"run": run, "scientific_replication_certified": False}
    pod.review(run["id"], "built-in synthetic smoke check", "engineering_verified")
    package = pod.export_package(run["id"])
    return {"run": run, "package": package, "verification": pod.verify_package(package["path"]),
            "scientific_replication_certified": False}


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            if not 1 <= args.port <= 65535:
                raise ValueError("port must be between 1 and 65535")
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(args.root), host="127.0.0.1", port=args.port)
            return 0
        if args.command == "doctor":
            _print(doctor())
            return 0
        if args.command == "case-status":
            from .cases import case_status
            _print(case_status())
            return 0
        if args.command == "lake-audit":
            if not args.database:
                raise ValueError("provide --database or AGH_DATA_LAKE_PATH")
            from .data_lake import audit_lake
            _print(audit_lake(args.database))
            return 0
        if args.command == "engine-probe":
            if not args.engine_root:
                raise ValueError("provide --engine-root or AGH_BACKTEST_ENGINE_ROOT")
            from .backends.nautilus import probe_backend
            result = probe_backend(args.engine_root, python_executable=args.python)
            _print(result)
            return 1 if result["status"] == "FAILED" else 0
        if args.command == "tushare-probe":
            from .providers.tushare import probe_tushare
            _print(probe_tushare())
            return 0
        if args.command == "price":
            from .pricing import contract_from_dict, price
            contract = contract_from_dict(json.loads(Path(args.path).read_text(encoding="utf-8")))
            _print(price(contract, args.model, steps=args.steps, paths=args.paths, seed=args.seed))
            return 0
        if args.command == "data-audit":
            from .cases import audit_dataset
            _print(audit_dataset(args.manifest))
            return 0
        if args.command == "package-verify":
            result = Pod.verify_package(args.path)
            _print(result)
            return 0 if result["valid"] else 1
        if args.command == "recover" and not args.workers_stopped:
            raise ValueError("stop workers first and explicitly pass --workers-stopped")
        pod = Pod(args.root)
        if args.command == "demo":
            result = _demo(pod)
        elif args.command == "import":
            path = Path(args.path)
            if path.suffix.lower() not in {".pdf", ".txt", ".md"}:
                raise ValueError("local evidence must be a PDF, TXT or Markdown file")
            if path.stat().st_size > 25_000_000:
                raise ValueError("artifact exceeds 25MB")
            result = pod.add_artifact("manual", args.title or path.name, path.read_bytes(), {"filename": path.name})
        elif args.command == "source-sync":
            from .sources import fetch_source
            fetched = fetch_source(args.source, args.reference)
            result = pod.add_artifact(args.source, fetched["title"], fetched["content"], fetched.get("metadata", {}))
        elif args.command == "analyze":
            result = pod.analyze_artifacts(args.artifact_ids, max_total_tokens=args.max_total_tokens,
                                           max_output_tokens=args.max_output_tokens)
        elif args.command == "list":
            result = pod.list(args.kind, limit=args.limit, offset=args.offset)
        elif args.command == "approve":
            result = pod.approve(args.spec_id)
        elif args.command == "run":
            result = pod.run_spec(args.spec_id, idempotency_key=args.idempotency_key)
        elif args.command == "worker":
            result = {"runs": [pod.execute(run["id"]) for run in pod.queued_runs()]}
        elif args.command == "recover":
            result = {"interrupted": pod.recover(), "workers_stopped": True}
        elif args.command == "quant-run":
            task_path = Path(args.task).resolve()
            task = json.loads(task_path.read_text(encoding="utf-8-sig"))
            payload = dict(task["experiment"])
            if payload.get("recipe") != "quant":
                raise ValueError("quant-run requires quant recipe")
            payload["dataset"] = str((task_path.parent / payload["dataset"]).resolve())
            op = pod.create_opportunity(task["title"], "investment_research", task["mandate"]["objective"])
            pod.set_mandate(op["id"], task["mandate"])
            artifact = pod.add_artifact("manual", task["title"], task_path.read_bytes(), {"kind":"authorized_task"})
            pod.link_artifact(op["id"], artifact["id"])
            spec = pod.create_spec(op["id"], payload)
            pod.approve(spec["id"])
            result = pod.run_spec(spec["id"])
        elif args.command == "review":
            result = pod.review(args.run_id, args.reviewer, args.decision)
        elif args.command == "package":
            result = pod.export_package(args.run_id)
        elif args.command == "receive":
            result = pod.receive_package(args.package_id, args.receiver, args.decision, args.reason)
        elif args.command == "research-start":
            from .research_agent import create_research, run_research
            path = Path(args.task).resolve()
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if payload.get("dataset"):
                payload["dataset"] = str((path.parent / payload["dataset"]).resolve())
            task = create_research(pod, payload)
            result = run_research(pod, task["id"], engine_root=args.engine_root, engine_python=args.engine_python)
        elif args.command == "research-export":
            from .research_agent import export_research
            result = export_research(pod, args.task_id)
        elif args.command == "case-run":
            payload = {"recipe": "paper", "dataset": str(Path(args.manifest).resolve())}
            previous = pod.get_request(args.idempotency_key) if args.idempotency_key else None
            if previous:
                if pod.get("spec", previous["spec"])["payload"] != payload:
                    raise StateError("idempotency conflict: key already used with another dataset or recipe")
                result = pod.execute(previous["run"])
            else:
                op = pod.create_opportunity("Convertible-bond paper dataset run", "investment_research")
                spec = pod.create_spec(op["id"], payload)
                pod.approve(spec["id"])
                result = pod.run_spec(spec["id"], idempotency_key=args.idempotency_key)
        else:
            raise ValueError("unknown command")
        _print(result)
        if isinstance(result, dict):
            runs = [result, result.get("run", {}), *result.get("runs", [])]
            if any(run.get("status") in {"failed", "FAILED", "BLOCKED_INPUT", "FAILED_MODEL", "BUDGET_EXHAUSTED", "BLOCKED_BACKTEST", "BLOCKED_METHOD", "BLOCKED_ENGINE_CONFIGURATION", "PROVIDER_BUDGET_OVERRUN"} for run in runs):
                return 1
        return 0
    except (ValueError, TypeError, KeyError, OSError, ImportError) as exc:
        _print({"error": str(exc), "error_type": type(exc).__name__}, error=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
