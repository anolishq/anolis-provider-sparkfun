"""What each supported SparkFun board provides to the provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from anolis_provider_sdk import DeviceType, Function

from ..mock import FakeChip


class NotAnswering(Exception):
    """Raised by a board module when the board at the address is absent, is a
    different chip, or has not finished starting. The provider reports the
    board UNREACHABLE and tries it again on the next read or call, as it does
    for a failed I2C transfer. Any other exception is a provider fault."""


class DeviceDriver:
    """One supported board: its ADPP declaration and a thin wrapper over the
    SparkFun driver. Construct it with an open qwiic_i2c bus, an address and the
    board's options from the config; the constructor raises NotAnswering, or
    lets the bus's OSError through, if the board does not answer there.

    A function whose category is CONFIG, that is idempotent and that takes at
    least one argument is a setting. The provider records the latest arguments
    of each setting called and, when it reconnects a board it had lost, calls
    them on the new driver in the order they were last set, so a setting
    survives a reconnect. Declare a function that way only if calling it again
    with the same arguments puts the setting back. A setting that fails to
    apply again leaves the board lost, like any failed transfer."""

    type: ClassVar[DeviceType]
    # Addresses the board can be strapped to. The first is the factory default.
    addresses: ClassVar[tuple[int, ...]]
    # JSON Schema of each per-device config key this board takes beyond id, type,
    # address and label. The schema's default is what the driver gets when the
    # config leaves the key out.
    options: ClassVar[Mapping[str, Mapping[str, Any]]] = {}

    def __init__(self, i2c: Any, address: int, options: Mapping[str, Any]) -> None:
        raise NotImplementedError

    @staticmethod
    def fake() -> FakeChip:
        """A register model of the chip, for mock mode."""
        raise NotImplementedError

    def read(self, signal_ids: list[str]) -> Mapping[str, Any]:
        raise NotImplementedError

    def call(self, function: Function, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        raise NotImplementedError
