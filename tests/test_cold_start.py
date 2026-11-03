"""scripts/cold_start.py: its hand-encoded frames, and a run against the provider."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from anolis.deviceprovider.v1 import envelope_pb2

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
