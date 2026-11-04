"""The boards this provider supports, by the ``type`` a config names them with."""

from __future__ import annotations

from .ads1015 import ADS1015
from .base import DeviceDriver, NotAnswering
from .bme280 import BME280
from .scd4x import SCD4x
from .scmd import SCMD
from .sht import SHTC3, SHT4x

KINDS: dict[str, type[DeviceDriver]] = {
    "ads1015": ADS1015,
    "bme280": BME280,
    "scd4x": SCD4x,
    "scmd": SCMD,
    "sht4x": SHT4x,
    "shtc3": SHTC3,
}

__all__ = ["KINDS", "DeviceDriver", "NotAnswering"]
