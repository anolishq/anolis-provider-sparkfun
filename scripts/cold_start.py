#!/usr/bin/env python3
"""Measure the provider's cold start: process launch to the Hello reply, and to
the WaitReady reply (start-up done, boards opened).

Needs only python3 and the provider binary, so it runs on a bare target:

    python3 cold_start.py /opt/anolis/bin/anolis-provider-sparkfun <config> [--runs 5]

The runtime gives a provider hello_timeout_ms (default 5000) to answer Hello,
and ready_timeout_ms to answer WaitReady. Exits 1 when the slowest Hello is
over --hello-budget-ms.
"""

from __future__ import annotations

import argparse
import statistics
import struct
import subprocess
import sys
import time
from typing import IO

# Request{request_id: 1, hello: {protocol_version: "v1"}} and
# Request{request_id: 2, wait_ready: {}}, serialized. tests/test_cold_start.py
# checks these against the anolis-protocol bindings.
HELLO = bytes.fromhex("080152040a027631")
WAIT_READY = bytes.fromhex("0802820100")


def frame(body: bytes) -> bytes:
    return struct.pack("<I", len(body)) + body


def read_frame(stream: IO[bytes]) -> bytes:
    header = stream.read(4)
    if len(header) != 4:
        raise RuntimeError("the provider closed stdout before replying")
    (length,) = struct.unpack("<I", header)
    return stream.read(length)


def one_run(binary: str, config: str) -> tuple[float, float]:
    began = time.monotonic()
    proc = subprocess.Popen([binary, "--config", config], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdin and proc.stdout
    try:
        proc.stdin.write(frame(HELLO))
        proc.stdin.flush()
        read_frame(proc.stdout)
        hello_ms = (time.monotonic() - began) * 1000
        proc.stdin.write(frame(WAIT_READY))
        proc.stdin.flush()
        read_frame(proc.stdout)
        ready_ms = (time.monotonic() - began) * 1000
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    return hello_ms, ready_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("binary")
    parser.add_argument("config")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--hello-budget-ms", type=float, default=5000.0)
    args = parser.parse_args()

    runs = [one_run(args.binary, args.config) for _ in range(args.runs)]
    hello = [h for h, _ in runs]
    ready = [r for _, r in runs]
    print(f"runs: {args.runs}")
    print(f"hello ms: median {statistics.median(hello):.0f}, max {max(hello):.0f} (budget {args.hello_budget_ms:.0f})")
    print(f"ready ms: median {statistics.median(ready):.0f}, max {max(ready):.0f}")
    return 1 if max(hello) > args.hello_budget_ms else 0


if __name__ == "__main__":
    sys.exit(main())
