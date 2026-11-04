"""Sensirion SCD40 and SCD41 on SparkFun boards: the Qwiic CO2 Humidity and
Temperature Sensor (SCD41: SEN-22396). True CO2 by NDIR, with temperature
and humidity (I2C 0x62).

Driver: sparkfun-qwiic-scd4x.

The sensor measures every 5 seconds on its own clock and a measurement can be
read out once, so a read returns the latest measurement with the time it was
fetched, and the same values again until the next one. Until the first one
arrives, about 5 seconds after start-up, every signal reads NaN with
QUALITY_UNKNOWN. A measurement older than two periods and a margin (12 s)
reads STALE, which shows a stuck sensor before the board restarts it.

Two things the driver does not do, done here:

- Its ``begin()`` returns True whatever its checks found. The board checks the
  serial number read itself, so a chip that does not answer as an SCD4x is
  reported unreachable.
- A sensor that restarted on its own (a brown-out) comes back idle and stops
  measuring, with nothing to show for it but a missing data-ready flag. When
  no measurement has arrived for four periods (20 s), the board starts the
  sensor again.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping
from typing import Any

import qwiic_scd4x
from anolis_provider_sdk import Arg, Category, DeviceType, Function, Quality, Reading, Signal, ValueType

from ..mock import FakeSCD4x
from .base import DeviceDriver, NotAnswering

log = logging.getLogger(__name__)

PERIOD_S = 5.0
# A measurement goes STALE before the board gives up on the sensor and restarts
# it, which clears the measurement: STALE is what a stuck sensor looks like.
STALE_AFTER_S = 2 * PERIOD_S + 2.0
RESTART_AFTER_S = 4 * PERIOD_S

TYPE = DeviceType(
    id="scd4x",
    signals=(
        Signal(
            "co2",
            ValueType.DOUBLE,
            unit="ppm",
            description="CO2 concentration, measured every 5 s",
            poll_hint_hz=0.2,
            stale_after_ms=int(STALE_AFTER_S * 1000),
        ),
        Signal(
            "temperature",
            ValueType.DOUBLE,
            unit="C",
            description="Temperature at the sensor, measured every 5 s",
            poll_hint_hz=0.2,
            stale_after_ms=int(STALE_AFTER_S * 1000),
        ),
        Signal(
            "relative_humidity",
            ValueType.DOUBLE,
            unit="%",
            description="Relative humidity at the sensor, measured every 5 s",
            poll_hint_hz=0.2,
            stale_after_ms=int(STALE_AFTER_S * 1000),
        ),
    ),
    functions=(
        Function(
            "set_ambient_pressure",
            description=(
                "Compensate the CO2 reading for the ambient pressure, for example from a BME280 on the same bus. "
                "Kept across a restart of the sensor and a reconnect of the board; not across a restart of the "
                "provider."
            ),
            args=(
                Arg(
                    "pressure",
                    ValueType.DOUBLE,
                    min=700.0,
                    max=1200.0,
                    unit="hPa",
                    description="Ambient pressure; the sensor's specified range",
                ),
            ),
            category=Category.CONFIG,
            is_idempotent=True,
        ),
    ),
)


class SCD4x(DeviceDriver):
    type = TYPE
    addresses = (0x62,)

    def __init__(self, i2c: Any, address: int, options: Mapping[str, Any]) -> None:
        self._address = address
        self._driver = qwiic_scd4x.QwiicSCD4x(address, i2c_driver=i2c)
        self._pressure_hpa: float | None = None
        self._setup()

    def _setup(self) -> None:
        d = self._driver
        # Stops any periodic measurement left running (waiting the sensor's
        # 500 ms), reads the serial number and the sensor type, and turns on
        # automatic self-calibration, the sensor's default.
        if not d.begin(measBegin=False):
            raise NotAnswering(f"no SCD4x at {self._address:#04x}")
        if d.get_serial_number() is None:
            raise NotAnswering(f"no SCD4x at {self._address:#04x}: its serial number did not read back intact")
        d.start_periodic_measurement()
        if self._pressure_hpa is not None:
            d.set_ambient_pressure(self._pressure_hpa * 100)
        self._started = time.monotonic()
        self._latest: dict[str, float] | None = None
        self._latest_at = 0.0  # time.time() when it was fetched
        self._latest_mono = 0.0

    @staticmethod
    def fake() -> FakeSCD4x:
        return FakeSCD4x()

    def _poll(self) -> None:
        d = self._driver
        if d.read_measurement():
            self._latest = {
                "co2": float(d.get_co2()),
                "temperature": float(d.get_temperature()),
                "relative_humidity": float(d.get_humidity()),
            }
            self._latest_at, self._latest_mono = time.time(), time.monotonic()
        elif time.monotonic() - (self._latest_mono or self._started) > RESTART_AFTER_S:
            log.warning("SCD4x at %#04x has stopped measuring; starting it again", self._address)
            self._setup()

    def read(self, signal_ids: list[str]) -> Mapping[str, Any]:
        self._poll()
        if self._latest is None:
            return {sid: Reading(math.nan, quality=Quality.UNKNOWN) for sid in signal_ids}
        return {sid: Reading(self._latest[sid], timestamp=self._latest_at) for sid in signal_ids}

    def call(self, function: Function, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if function.name == "set_ambient_pressure":
            self._pressure_hpa = float(args["pressure"])
            self._driver.set_ambient_pressure(self._pressure_hpa * 100)
        return None
