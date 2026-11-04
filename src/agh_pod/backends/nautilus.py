"""Use the user-selected engine in a separate, version-qualified Python process."""

import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

ENGINE_URL = "https://github.com/DFPite174/ashare-nautilus-backtest-engine"
ENGINE_REVISION = "b8d424df1a7c7c65b29eaab1be667a5368c8be5c"


def inspect_backend(engine_root):
    root = Path(engine_root).resolve()
    if not (root / "engine" / "backtest.py").is_file() or not (root / "contracts" / "models.py").is_file():
        raise ValueError("backtest engine repository not found")
    git = os.getenv("AGH_GIT") or shutil.which("git") or "git"
    result = subprocess.run([git, "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                            text=True, timeout=10, check=False)
    if result.returncode:
        raise ValueError("engine repository must have verifiable Git revision")
    dirty = subprocess.run([git, "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, timeout=10, check=False)
    revision = result.stdout.strip()
    return {"repository": ENGINE_URL, "revision": revision, "expected_revision": ENGINE_REVISION,
            "version_matches": revision == ENGINE_REVISION,
            "tracked_worktree_clean": dirty.returncode == 0 and not dirty.stdout.strip(),
            "paper_short_leg_supported": False, "convertible_cashflow_events_qualified": False}


def _invoke(engine_root, payload, *, python_executable=None, process=None):
    process = process or subprocess.run
    python_executable = python_executable or os.getenv("AGH_ENGINE_PYTHON") or sys.executable
    worker = Path(__file__).with_name("engine_worker.py")
    request = {**payload, "engine_root": str(Path(engine_root).resolve())}
    try:
        completed = process([str(python_executable), "-X", "utf8", str(worker)],
                            input=json.dumps(request, allow_nan=False), capture_output=True,
                            text=True, timeout=120, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "FAILED", "reason": "engine worker failed or exceeded120s", "repository": ENGINE_URL}
    if completed.returncode:
        return {"status": "FAILED", "reason": "engine worker exited unsuccessfully", "repository": ENGINE_URL}
    try:
        # Native NT may log to stdout; only the marked result is protocol data.
        raw = completed.stdout.rsplit("AGH_RESULT=", 1)[-1].strip()
        result = json.loads(raw)
        if not isinstance(result, dict) or "status" not in result:
            raise ValueError
        return result
    except (ValueError, TypeError):
        return {"status": "FAILED", "reason": "invalid engine worker result", "repository": ENGINE_URL}


def probe_backend(engine_root, *, python_executable=None):
    return _invoke(engine_root, {"action": "probe"}, python_executable=python_executable)


def run_account_backtest(engine_root, request, *, python_executable=None, process=None):
    if request.get("asset_class") != "CONVERTIBLE_BOND":
        raise ValueError("this paper adapter requires an explicit CONVERTIBLE_BOND asset class")
    return _invoke(engine_root, {**request, "action": "run"},
                   python_executable=python_executable, process=process)


def run_equity_backtest(engine_root, request, *, python_executable=None, process=None):
    if request.get("asset_class") != "EQUITY":
        raise ValueError("ordinary equity adapter requires EQUITY")
    return _invoke(engine_root, {**request, "action": "equity"},
                   python_executable=python_executable, process=process)
