"""The boards this provider supports, by the ``type`` a config names them with."""

from __future__ import annotations

from .ads1015 import ADS1015
from .base import DeviceDriver
from .bme280 import BME280
from .scd4x import SCD4x
from .scmd import SCMD

KINDS: dict[str, type[DeviceDriver]] = {
    "ads1015": ADS1015,
    "bme280": BME280,
    "scd4x": SCD4x,
    "scmd": SCMD,
}

__all__ = ["KINDS", "DeviceDriver"]
