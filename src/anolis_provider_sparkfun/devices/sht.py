"""Sensirion SHT4x (SHT40, SHT41, SHT45) and SHTC3 temperature and humidity
sensors on SparkFun Qwiic boards (SHT4x at I2C 0x44, SHTC3 at 0x70).

Drivers: ``anolis_qwiic_staging.qwiic_sht4x`` and ``qwiic_shtc3``, written for
this provider because SparkFun's Qwiic Python package has none for these
chips, and staged to go to SparkFun once proven on hardware. The device types
are the ones the Adafruit provider declares for the same chips.

A board is refused unless its id check passes (the SHT4x serial number with
intact CRCs, the SHTC3 id register); a board that does not answer at all is
reported as the bus error. A reading that fails its CRC is reported
as a failed transfer, so the provider retries the board rather than passing
on a bad value.
"""

from __future__ import annotations

import errno
from collections.abc import Mapping
from typing import Any

from anolis_provider_sdk import DeviceType, Function, Signal, ValueType

from anolis_qwiic_staging.qwiic_sht4x import QwiicSHT4x
from anolis_qwiic_staging.qwiic_shtc3 import QwiicSHTC3

from ..mock import FakeSHT4x, FakeSHTC3
from .base import DeviceDriver, NotAnswering

SIGNALS = (
    Signal("temperature", ValueType.DOUBLE, unit="C", description="Air temperature"),
    Signal("relative_humidity", ValueType.DOUBLE, unit="%", description="Relative humidity"),
)


class _SensirionHumidity(DeviceDriver):
    _name: str
    _sensor: Any

    def __init__(self, i2c: Any, address: int, options: Mapping[str, Any]) -> None:
        self._address = address
        self._sensor = self._open(i2c, address)
        if not self._sensor.begin():
            raise NotAnswering(f"no {self._name} at {address:#04x}: it did not pass its id check")

    def _open(self, i2c: Any, address: int) -> Any:
        raise NotImplementedError

    def read(self, signal_ids: list[str]) -> Mapping[str, Any]:
        result = self._sensor.measure()
        if result is None:
            raise OSError(errno.EIO, f"{self._name} at {self._address:#04x}: reading failed its CRC")
        values = {"temperature": result[0], "relative_humidity": result[1]}
        return {sid: float(values[sid]) for sid in signal_ids}

    def call(self, function: Function, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        raise NotImplementedError(f"the {self._name} declares no functions")


class SHT4x(_SensirionHumidity):
    type = DeviceType(id="sht4x", signals=SIGNALS)
    addresses = (0x44,)
    _name = "SHT4x"

    def _open(self, i2c: Any, address: int) -> Any:
        sensor = QwiicSHT4x(address, i2c_driver=i2c)
        # begin() returns False both when nothing answers and when the id
        # check fails; nothing answering is a bus error, as on the SHTC3.
        if not sensor.is_connected():
            raise OSError(errno.ENXIO, f"nothing acknowledges {address:#04x}")
        return sensor

    @staticmethod
    def fake() -> FakeSHT4x:
        return FakeSHT4x()


class SHTC3(_SensirionHumidity):
    type = DeviceType(id="shtc3", signals=SIGNALS)
    addresses = (0x70,)
    _name = "SHTC3"

    def _open(self, i2c: Any, address: int) -> Any:
        return QwiicSHTC3(address, i2c_driver=i2c)

    @staticmethod
    def fake() -> FakeSHTC3:
        return FakeSHTC3()
