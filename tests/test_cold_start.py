"""scripts/cold_start.py: its hand-encoded frames, and a run against the provider."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from anolis.deviceprovider.v1 import envelope_pb2, status_pb2

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "cold_start.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cold_start", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_frames_match_the_protocol_bindings() -> None:
    cold_start = load()
    hello = envelope_pb2.Request(request_id=1)
    hello.hello.protocol_version = "v1"
    wait_ready = envelope_pb2.Request(request_id=2)
    wait_ready.wait_ready.SetInParent()
    assert cold_start.HELLO == hello.SerializeToString()
    assert cold_start.WAIT_READY == wait_ready.SerializeToString()


def test_it_measures_the_provider_in_mock_mode() -> None:
    provider = shutil.which("anolis-provider-sparkfun", path=str(Path(sys.executable).parent))
    assert provider
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), provider, str(REPO / "config" / "conformance.yaml"), "--runs", "2"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "hello ms: median" in proc.stdout and "ready ms: median" in proc.stdout


def response(code: int, *, ready: str | None = None, start_error: str = "") -> bytes:
    r = envelope_pb2.Response(request_id=2)
    r.status.code = code
    if code != status_pb2.Status.CODE_OK:
        r.status.message = "it went wrong"
    if ready is not None:
        r.wait_ready.diagnostics["ready"] = ready
        r.wait_ready.diagnostics["init_time_ms"] = "12"
        if start_error:
            r.wait_ready.diagnostics["start_error"] = start_error
    return bytes(r.SerializeToString())


def test_a_reply_is_checked_for_its_status_and_readiness() -> None:
    cold_start = load()
    ok = status_pb2.Status.CODE_OK
    cold_start.check_reply("Hello", response(ok))
    cold_start.check_reply("WaitReady", response(ok, ready="true"))
    with pytest.raises(cold_start.ColdStartError, match="Hello returned status code 12: it went wrong"):
        cold_start.check_reply("Hello", response(status_pb2.Status.CODE_FAILED_PRECONDITION))
    with pytest.raises(cold_start.ColdStartError, match="not ready: OSError: cannot open"):
        cold_start.check_reply("WaitReady", response(ok, ready="false", start_error="OSError: cannot open"))
    with pytest.raises(cold_start.ColdStartError, match="status code 0"):
        cold_start.check_reply("Hello", envelope_pb2.Response(request_id=1).SerializeToString())


@pytest.mark.parametrize("ready", ["false", None])
def test_an_ok_wait_ready_that_is_not_ready_fails_without_a_start_error(ready: str | None) -> None:
    # The SDK answers WaitReady OK with ready=false and no start_error when a
    # host requirement is unmet, so the ready flag itself is what is checked,
    # not the status code or the presence of start_error.
    cold_start = load()
    reply = response(status_pb2.Status.CODE_OK, ready=ready)
    with pytest.raises(cold_start.ColdStartError, match="not ready"):
        cold_start.check_reply("WaitReady", reply)


def test_it_fails_when_the_provider_is_not_ready(tmp_path: Path) -> None:
    # /dev/i2c-99 does not exist, so the host check at start-up is unmet: both
    # replies are OK and only WaitReady's ready flag says the provider is not up.
    provider = shutil.which("anolis-provider-sparkfun", path=str(Path(sys.executable).parent))
    assert provider
    config = tmp_path / "config.yaml"
    config.write_text("i2c_bus: 99\ndevices:\n  - id: rh0\n    type: sht4x\n")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), provider, str(config), "--runs", "1"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1
    assert "cold_start: WaitReady: the provider is not ready" in proc.stderr
    assert "/dev/i2c-99" in proc.stderr  # from the provider's own log, which shares stderr
    assert "ready ms" not in proc.stdout
