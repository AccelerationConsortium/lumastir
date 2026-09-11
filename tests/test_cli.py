import io
import json
import subprocess
import sys
import urllib.error
from unittest.mock import patch

import pytest

from lumastir.cli import main, send_request


def test_remote_cli_import_never_loads_hardware():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import lumastir.cli, sys; assert 'board' not in sys.modules; assert 'RPi.GPIO' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_http_error_body_is_preserved():
    error = urllib.error.HTTPError(
        "http://example",
        423,
        "Locked",
        {},
        io.BytesIO(b'{"error":{"code":"claim_required"}}'),
    )
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="claim_required"):
            send_request("/control/motor/set", {"index": 0, "speed": 50}, "POST")


def test_timeout_is_explicit_and_empty_json_is_sent():
    with patch("urllib.request.urlopen") as mocked:
        mocked.return_value.__enter__.return_value = io.BytesIO(b'{"status":"ok"}')
        assert send_request("/control/stop", {}, "POST", timeout=3)["status"] == "ok"
        assert mocked.call_args.kwargs["timeout"] == 3
        assert mocked.call_args.args[0].data == b"{}"


def test_cli_failure_goes_to_stderr_and_sets_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["lumastir-cli", "status"])
    with patch("lumastir.cli.send_request", side_effect=RuntimeError("offline")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "offline" in captured.err


def test_cli_run_releases_if_start_response_is_lost(monkeypatch, capsys):
    monkeypatch.setattr(
        sys, "argv", ["lumastir-cli", "run", "0", "50", "20", "--owner", "test"]
    )
    from uuid import uuid4

    instance = str(uuid4())
    with patch(
        "lumastir.cli.send_request",
        side_effect=[
            {"instance_id": instance},
            {"claim_token": "test-secret", "heartbeat_interval_s": 10},
            RuntimeError("response lost"),
            {"status": "ok"},
        ],
    ) as mocked:
        with pytest.raises(SystemExit):
            main()
        assert mocked.call_args_list[-1].args[0] == "/control/release"
        assert mocked.call_args_list[-1].kwargs["token"] == "test-secret"
    output = capsys.readouterr()
    assert json.loads(output.out)["request_id"]
    assert "response lost" in output.err
