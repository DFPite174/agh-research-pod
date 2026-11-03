import json
import subprocess
import sys

import pytest

from agh_pod.backends.nautilus import ENGINE_REVISION, inspect_backend, run_account_backtest


def test_engine_revision_required_and_missing_root_refused(tmp_path):
    with pytest.raises(ValueError, match="repository"):
        inspect_backend(tmp_path)


def test_convertible_failure_is_not_relabelled_as_equity(tmp_path):
    # A controlled worker response crosses the same process seam as the real engine.
    response = dict(status="BLOCKED_ENGINE_CAPABILITY", engine_revision=ENGINE_REVISION,
                    convertible_instrument_accepted=False,
                    reason="Only Shanghai/Shenzhen cash equities are supported")
    def process(args, **kwargs):
        assert kwargs["input"]
        request = json.loads(kwargs["input"])
        assert request["action"] == "run"
        assert request["asset_class"] == "CONVERTIBLE_BOND"
        return subprocess.CompletedProcess(args, 0, json.dumps(response), "")
    result = run_account_backtest(tmp_path, {"asset_class": "CONVERTIBLE_BOND", "bars": []},
                                  python_executable=sys.executable, process=process)
    assert result["status"] == "BLOCKED_ENGINE_CAPABILITY"
    assert not result["convertible_instrument_accepted"]
    assert "nav" not in result


def test_process_error_is_not_successful_backtest(tmp_path):
    def process(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "private-provider-detail")
    result = run_account_backtest(tmp_path, {"asset_class": "CONVERTIBLE_BOND"}, process=process)
    assert result["status"] == "FAILED"
    assert "private-provider-detail" not in json.dumps(result)
