"""The provider: SparkFun Qwiic boards on one I2C bus, each driven by SparkFun's own driver.

Devices come from the config and stay listed for the life of the process. A
board that does not answer at start-up, or stops answering, is reported
UNREACHABLE and retried on the next read or call, so a loose cable recovers
without a restart.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from anolis_provider_sdk import (
    Device,
    DeviceHealth,
    DeviceState,
    Function,
    Health,
    HealthState,
    HostRequirement,
    Provider,
    ProviderError,
    StatusCode,
    run,
)

from .devices import KINDS, DeviceDriver, NotAnswering
from .mock import FakeQwiicBus

log = logging.getLogger("anolis_provider_sparkfun")

# What a failed I2C transfer looks like from Linux: the board did not acknowledge
# (ENXIO, EREMOTEIO), the transfer failed or timed out (EIO, ETIMEDOUT), or the
# bus was busy (EAGAIN). Any other OSError, such as a missing file, is a fault in
# the provider rather than an absent board, and is not reported as UNREACHABLE.
_BUS_ERRNOS = {errno.ENXIO, errno.EREMOTEIO, errno.EIO, errno.ETIMEDOUT, errno.EAGAIN}


def _not_answering(err: Exception) -> bool:
    """Whether an exception from a board means the board is not answering: a
    failed I2C transfer, or a board module's NotAnswering. Anything else is a
    fault in the provider."""
    return isinstance(err, NotAnswering) or (isinstance(err, OSError) and err.errno in _BUS_ERRNOS)


try:
    __version__ = version("anolis-provider-sparkfun")
except PackageNotFoundError:  # a source tree that is not installed
    __version__ = "0.0.0"


def _device_schema() -> dict[str, Any]:
    # Every board's options are declared at the top, so additionalProperties
    # sees them; each kind then refuses the options that are not its own.
    all_options = {name: dict(schema) for cls in KINDS.values() for name, schema in cls.options.items()}
    per_kind = [
        {
            "if": {"properties": {"type": {"const": kind}}},
            "then": {
                "properties": {
                    "address": {"enum": list(cls.addresses)},
                    **{name: False for name in all_options if name not in cls.options},
                }
            },
        }
        for kind, cls in KINDS.items()
    ]
    return {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "pattern": "^[a-z][a-z0-9_]*$",
                "description": "Device id, stable across restarts",
            },
            "type": {"enum": sorted(KINDS), "description": "Which board"},
            "address": {
                "type": "integer",
                "description": "I2C address; defaults to the board's factory address",
            },
            "label": {"type": "string"},
            **all_options,
        },
        "required": ["id", "type"],
        "additionalProperties": False,
        "allOf": per_kind,
    }


CONFIG_SCHEMA: dict[str, Any] = {
    "title": "anolis-provider-sparkfun config",
    "type": "object",
    "properties": {
        "i2c_bus": {
            "type": "integer",
            "minimum": 0,
            "default": 1,
            "description": "Linux I2C bus number, /dev/i2c-<n>. 1 is the Raspberry Pi header.",
        },
        "mock": {
            "type": "boolean",
            "default": False,
            "description": "Use a simulated bus with a register model of each configured board instead of hardware",
        },
        "devices": {"type": "array", "minItems": 1, "items": _device_schema()},
    },
    "required": ["devices"],
    "additionalProperties": False,
}


def bus_device(bus: int) -> str:
    """The Linux device node for an I2C bus number."""
    return f"/dev/i2c-{bus}"


def open_bus(bus: int) -> Any:
    """SparkFun's Linux bus driver on /dev/i2c-<bus>."""
    from qwiic_i2c.linux_i2c import LinuxI2C

    driver = LinuxI2C(iBus=bus)
    # LinuxI2C prints and carries on with no bus when the open fails.
    if driver.i2cbus is None:
        raise OSError(errno.ENODEV, f"cannot open {bus_device(bus)}")
    return driver


class _Slot:
    """One configured board and its driver, when it is answering."""

    def __init__(self, kind: type[DeviceDriver], address: int, options: Mapping[str, Any]) -> None:
        self.kind = kind
        self.address = address
        self.options = options
        self.driver: DeviceDriver | None = None
        self.error = "not started"


class SparkFunProvider(Provider):
    name = "anolis-provider-sparkfun"
    version = __version__
    conformance_level = 2
    config_schema = CONFIG_SCHEMA

    def __init__(self, config: Mapping[str, Any]) -> None:
        super().__init__(config)
        self._devices: list[Device] = []
        self._slots: dict[str, _Slot] = {}
        claimed: dict[int, str] = {}
        for entry in config["devices"]:
            kind = KINDS[entry["type"]]
            address = entry.get("address", kind.addresses[0])
            if entry["id"] in self._slots:
                raise ValueError(f"device id {entry['id']!r} is configured twice")
            if address in claimed:
                raise ValueError(
                    f"I2C address {address:#04x} is configured for both {claimed[address]!r} and {entry['id']!r}"
                )
            claimed[address] = entry["id"]
            options = {name: entry.get(name, schema.get("default")) for name, schema in kind.options.items()}
            self._slots[entry["id"]] = _Slot(kind, address, options)
            self._devices.append(
                Device(
                    entry["id"],
                    kind.type,
                    label=entry.get("label", entry["id"]),
                    address=f"i2c-{config.get('i2c_bus', 1)}:{address:#04x}",
                )
            )
        self._bus: Any = None
        self._started = False
        self._bus_error: str | None = None

    # ---- lifecycle ----------------------------------------------------------------

    def start(self, budget_s: float) -> None:
        self._started = True
        try:
            if self.config.get("mock", False):
                self._bus = FakeQwiicBus({s.address: s.kind.fake() for s in self._slots.values()})
            else:
                self._bus = open_bus(self.config.get("i2c_bus", 1))
        except Exception as err:
            # Every board is unreachable, and says why.
            self._bus_error = f"the I2C bus did not open: {err}"
            for slot in self._slots.values():
                slot.error = self._bus_error
            raise
        for device_id, slot in self._slots.items():
            self._connect(device_id, slot)

    def _connect(self, device_id: str, slot: _Slot) -> DeviceDriver | None:
        try:
            slot.driver = slot.kind(self._bus, slot.address, slot.options)
        except (OSError, NotAnswering) as err:
            if not _not_answering(err):
                raise
            slot.driver = None
            slot.error = f"{slot.kind.type.id} at {slot.address:#04x}: {err}"
            log.warning("%s: %s", device_id, slot.error)
        return slot.driver

    # ---- ADPP -----------------------------------------------------------------------

    def devices(self) -> Sequence[Device]:
        return self._devices

    def _driver(self, device: Device) -> DeviceDriver:
        slot = self._slots[device.id]
        driver = slot.driver or (self._connect(device.id, slot) if self._bus is not None else None)
        if driver is None:
            raise ProviderError(StatusCode.UNAVAILABLE, f"{device.id} is not answering: {slot.error}")
        return driver

    def _lost(self, device: Device, err: Exception) -> ProviderError:
        slot = self._slots[device.id]
        slot.driver = None
        slot.error = f"{slot.kind.type.id} at {slot.address:#04x}: {err}"
        log.warning("%s: %s", device.id, slot.error)
        return ProviderError(StatusCode.UNAVAILABLE, f"{device.id} stopped answering: {err}")

    def read(self, device: Device, signal_ids: list[str]) -> Mapping[str, Any]:
        driver = self._driver(device)
        try:
            return driver.read(signal_ids)
        except (OSError, NotAnswering) as err:
            if not _not_answering(err):
                raise
            raise self._lost(device, err) from err

    def call(self, device: Device, function: Function, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        driver = self._driver(device)
        try:
            return driver.call(function, args)
        except (OSError, NotAnswering) as err:
            if not _not_answering(err):
                raise
            raise self._lost(device, err) from err

    def health(self) -> Health:
        if self._bus_error is not None:
            return Health(HealthState.FAULT, self._bus_error)
        down = [device_id for device_id, slot in self._slots.items() if slot.driver is None]
        if down and self._started:
            return Health(HealthState.DEGRADED, f"not answering: {', '.join(down)}")
        return Health()

    def device_health(self, device: Device) -> DeviceHealth | None:
        slot = self._slots[device.id]
        if slot.driver is None and self._started:
            return DeviceHealth(DeviceState.UNREACHABLE, slot.error)
        return None

    # ---- executable profile §6 --------------------------------------------------------

    @classmethod
    def check_host(cls, config: Mapping[str, Any]) -> Sequence[HostRequirement]:
        if config.get("mock", False):
            return []
        path = bus_device(config.get("i2c_bus", 1))
        if not os.path.exists(path):
            return [
                HostRequirement(
                    "i2c_bus",
                    "unmet",
                    detail=f"{path} does not exist",
                    remedy="enable I2C (on Raspberry Pi OS: sudo raspi-config nonint do_i2c 0), then reboot",
                )
            ]
        if not os.access(path, os.R_OK | os.W_OK):
            return [
                HostRequirement(
                    "i2c_bus",
                    "unmet",
                    detail=f"{path} is not readable and writable by this user",
                    remedy="add the service user to the i2c group: sudo usermod -aG i2c anolis",
                )
            ]
        return [HostRequirement("i2c_bus", "met", detail=f"{path} is accessible")]


def main() -> None:
    sys.exit(run(SparkFunProvider))
