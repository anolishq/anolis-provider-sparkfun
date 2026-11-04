"""The provider, in mock mode, under the anolis-protocol conformance harness.

The test requires zero failures and lists every allowed skip with its reason.
Set ANOLIS_PROVIDER_BIN to run it against another build of the provider, such
as the frozen release binary.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

EXPECTED_SKIPS: dict[str, str] = {
    "test_call_declared_results_are_populated": (
        "no function here takes no arguments and returns a result; the motor driver has no such operation"
    ),
    "test_call_valid_no_arg_function_accepted": (
        "every function here drives a motor and takes its throttle; a no-argument one would be invented for the test"
    ),
}


@pytest.mark.conformance
def test_provider_passes_the_harness(tmp_path: Path) -> None:
    bindir = str(Path(sys.executable).parent)
    harness = shutil.which("anolis-adpp-conformance", path=bindir)
    provider = os.environ.get("ANOLIS_PROVIDER_BIN") or shutil.which("anolis-provider-sparkfun", path=bindir)
    assert harness and provider, "install the dev extra (uv sync --extra dev)"
    report = tmp_path / "report.xml"
    proc = subprocess.run(
        [
            harness,
            "--provider-bin",
            provider,
            "--provider-config",
            str(REPO / "config" / "conformance.yaml"),
            "--provider-profile",
            str(REPO / "config" / "conformance.toml"),
            f"--junitxml={report}",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=tmp_path,
    )
    cases = list(ET.parse(report).iter("testcase"))
    failed = [c.get("name") for c in cases if c.find("failure") is not None or c.find("error") is not None]
    skipped = {c.get("name"): (s.get("message") or "") for c in cases if (s := c.find("skipped")) is not None}
    passed = len(cases) - len(skipped) - len(failed)
    print(f"harness against {provider}: {passed} passed, {len(skipped)} skipped, {len(failed)} failed")
    assert proc.returncode == 0 and not failed, f"failed: {failed}\n{proc.stdout[-4000:]}"
    unexpected = {name: why for name, why in skipped.items() if name not in EXPECTED_SKIPS}
    assert not unexpected, f"unexpected skips: {unexpected}"
    assert passed > 40, f"only {passed} cases passed"
