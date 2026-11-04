#!/usr/bin/env python3
"""Measure the provider's cold start: process launch to the Hello reply, and to
the WaitReady reply (start-up done, boards opened).

Needs only python3 and the provider binary, so it runs on a bare target:

    python3 cold_start.py /opt/anolis/bin/anolis-provider-<name> <config> [--runs 5]

The runtime gives a provider hello_timeout_ms (default 5000) to answer Hello,
and ready_timeout_ms to answer WaitReady. Exits 1 when the slowest Hello is
over --hello-budget-ms, and exits 1 without a figure when a Hello or WaitReady
reply is not OK or the provider reports it is not ready (its start failed).
"""

from __future__ import annotations

import argparse
import statistics
import struct
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import IO

# Request{request_id: 1, hello: {protocol_version: "v1"}} and
# Request{request_id: 2, wait_ready: {}}, serialized. tests/test_cold_start.py
# checks these against the anolis-protocol bindings.
HELLO = bytes.fromhex("080152040a027631")
WAIT_READY = bytes.fromhex("0802820100")

# Field numbers in the replies: Response.status = 2, Status.code = 1 and
# .message = 2, Response.wait_ready = 16, WaitReadyResponse.diagnostics = 1
# (map entries: key = 1, value = 2). CODE_OK is 1.
STATUS, CODE, MESSAGE, WAIT_READY_REPLY, DIAGNOSTICS = 2, 1, 2, 16, 1
CODE_OK = 1


class ColdStartError(Exception):
    """The provider did not start: a reply that is not OK, or not ready."""


def _varint(data: bytes, i: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if i >= len(data):
            raise ColdStartError("a reply ends inside a field")
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, i


def fields(data: bytes) -> Iterator[tuple[int, int | bytes]]:
    """The (field number, value) pairs of a serialized protobuf message: an
    int for a varint, bytes for anything length-delimited or fixed-size."""
    i = 0
    while i < len(data):
        key, i = _varint(data, i)
        number, wire = key >> 3, key & 0x7
        value: int | bytes
        if wire == 0:
            value, i = _varint(data, i)
        elif wire == 2:
            length, i = _varint(data, i)
            value, i = data[i : i + length], i + length
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value, i = data[i : i + size], i + size
        else:
            raise ColdStartError(f"a reply has a field of wire type {wire}")
        yield number, value


def _bytes(value: int | bytes) -> bytes:
    return value if isinstance(value, bytes) else b""


def check_reply(name: str, reply: bytes) -> None:
    """Raise ColdStartError unless the reply's status is OK and, for
    WaitReady, the provider reports it is ready."""
    top = list(fields(reply))
    code, message = 0, ""
    for number, value in top:
        if number == STATUS:
            for n, v in fields(_bytes(value)):
                if n == CODE and isinstance(v, int):
                    code = v
                elif n == MESSAGE:
                    message = _bytes(v).decode(errors="replace")
    if code != CODE_OK:
        raise ColdStartError(f"{name} returned status code {code}: {message or '(no message)'}")
    if name != "WaitReady":
        return
    diagnostics: dict[str, str] = {}
    for number, value in top:
        if number == WAIT_READY_REPLY:
            for n, entry in fields(_bytes(value)):
                if n == DIAGNOSTICS:
                    kv = dict(fields(_bytes(entry)))
                    diagnostics[_bytes(kv.get(1, b"")).decode()] = _bytes(kv.get(2, b"")).decode()
    if diagnostics.get("ready") != "true":
        raise ColdStartError(
            f"WaitReady: the provider is not ready: {diagnostics.get('start_error', '(no start_error given)')}"
        )


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
        hello = read_frame(proc.stdout)
        hello_ms = (time.monotonic() - began) * 1000
        check_reply("Hello", hello)
        proc.stdin.write(frame(WAIT_READY))
        proc.stdin.flush()
        ready = read_frame(proc.stdout)
        ready_ms = (time.monotonic() - began) * 1000
        check_reply("WaitReady", ready)
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

    try:
        runs = [one_run(args.binary, args.config) for _ in range(args.runs)]
    except ColdStartError as err:
        print(f"cold_start: {err}", file=sys.stderr)
        return 1
    hello = [h for h, _ in runs]
    ready = [r for _, r in runs]
    print(f"runs: {args.runs}")
    print(f"hello ms: median {statistics.median(hello):.0f}, max {max(hello):.0f} (budget {args.hello_budget_ms:.0f})")
    print(f"ready ms: median {statistics.median(ready):.0f}, max {max(ready):.0f}")
    return 1 if max(hello) > args.hello_budget_ms else 0


if __name__ == "__main__":
    sys.exit(main())
