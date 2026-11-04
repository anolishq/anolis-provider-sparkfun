"""Bosch BME280 on SparkFun boards: the Qwiic Atmospheric Sensor (SEN-15440) and
the BME280 half of the Environmental Combo (SEN-22858). Temperature, humidity
and pressure (I2C 0x77 by default, 0x76 with the address jumper).

Driver: sparkfun-qwiic-bme280. The device type is the one the Adafruit
provider declares for the same chip, so a BME280 reads the same through either.

Three things the driver does not do, done here:

- It accepts a BMP280 (chip id 0x58), which has no humidity sensor. The board
  refuses it, so ``relative_humidity`` is never a number the chip cannot give.
- Its ``begin()`` reports a wrong chip by printing and returning False. The
  board raises instead, so the address is reported unreachable.
- A chip that restarted on its own (a brown-out) comes back asleep, with its
  data registers at reset values that convert to plausible readings. The board
  checks the mode on every read and sets the chip up again when it finds it
  asleep.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import qwiic_bme280
from anolis_provider_sdk import Arg, Category, DeviceType, Function, Signal, ValueType

from ..mock import FakeBME280
from .base import DeviceDriver

log = logging.getLogger(__name__)

CHIP_ID = 0x60  # BME280; 0x58 is the BMP280
SOFT_RESET = 0xB6
IM_UPDATE = 0x01  # status bit 0: calibration still being copied from NVM
STARTUP_TIMEOUT_S = 0.05  # datasheet t_startup is 2 ms
SEA_LEVEL_DEFAULT_HPA = 1013.25

TYPE = DeviceType(
    id="bme280",
    signals=(
        Signal("temperature", ValueType.DOUBLE, unit="C", description="Air temperature"),
        Signal("relative_humidity", ValueType.DOUBLE, unit="%", description="Relative humidity"),
        Signal("pressure", ValueType.DOUBLE, unit="hPa", description="Barometric pressure"),
        Signal(
            "altitude",
            ValueType.DOUBLE,
            unit="m",
            description="Altitude estimated from pressure and the sea-level pressure",
            default=False,
            poll_hint_hz=0.0,
        ),
        Signal(
            "sea_level_pressure",
            ValueType.DOUBLE,
            unit="hPa",
            description="Sea-level pressure the altitude estimate uses",
            default=False,
            poll_hint_hz=0.0,
        ),
    ),
    functions=(
        Function(
            "set_sea_level_pressure",
            description="Set the local sea-level pressure, which calibrates the altitude estimate",
            args=(
                Arg(
                    "sea_level_pressure",
                    ValueType.DOUBLE,
                    min=870.0,
                    max=1085.0,
                    unit="hPa",
                    description="Local sea-level pressure; the recorded extremes bound it",
                ),
            ),
            category=Category.CONFIG,
            is_idempotent=True,
        ),
        Function(
            "soft_reset",
            description="Reset the sensor and reapply its settings, the sea-level pressure included",
            category=Category.CONFIG,
            is_idempotent=True,
        ),
    ),
)


class BME280(DeviceDriver):
    type = TYPE
    addresses = (0x77, 0x76)

    def __init__(self, i2c: Any, address: int, options: Mapping[str, Any]) -> None:
        self._bus = i2c
        self._address = address
        self._driver = qwiic_bme280.QwiicBme280(address, i2c_driver=i2c)
        self._sea_level_hpa = SEA_LEVEL_DEFAULT_HPA
        self._setup()

    def _setup(self) -> None:
        found = int(self._bus.readByte(self._address, qwiic_bme280.QwiicBme280.BME280_CHIP_ID_REG))
        if found != CHIP_ID:
            kind = "a BMP280, which has no humidity sensor" if found == 0x58 else f"chip id {found:#04x}"
            raise ValueError(f"no BME280 at {self._address:#04x}: found {kind}")
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while int(self._bus.readByte(self._address, qwiic_bme280.QwiicBme280.BME280_STAT_REG)) & IM_UPDATE:
            if time.monotonic() > deadline:
                raise RuntimeError(f"BME280 at {self._address:#04x} has not finished starting up")
            time.sleep(0.001)
        # Calibration read, 1x oversampling on all three, normal mode, and a
        # wait for the first measurement.
        if not self._driver.begin():
            raise ValueError(f"no BME280 at {self._address:#04x}")

    @staticmethod
    def fake() -> FakeBME280:
        return FakeBME280()

    def _check_restarted(self) -> None:
        if self._driver.get_mode() != qwiic_bme280.QwiicBme280.MODE_NORMAL:
            log.warning("BME280 at %#04x restarted; setting it up again", self._address)
            self._setup()

    def read(self, signal_ids: list[str]) -> Mapping[str, Any]:
        self._check_restarted()
        d = self._driver
        d.set_reference_pressure(self._sea_level_hpa * 100)
        getters = {
            "temperature": d.get_temperature_celsius,
            "relative_humidity": d.read_humidity,
            "pressure": lambda: d.read_pressure() / 100,
            "altitude": d.get_altitude_meters,
            "sea_level_pressure": lambda: self._sea_level_hpa,
        }
        return {sid: float(getters[sid]()) for sid in signal_ids}

    def call(self, function: Function, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if function.name == "set_sea_level_pressure":
            self._sea_level_hpa = float(args["sea_level_pressure"])
        elif function.name == "soft_reset":
            self._driver.reset()
            time.sleep(0.002)  # t_startup: the chip does not answer until it has restarted
            self._setup()
        return None
