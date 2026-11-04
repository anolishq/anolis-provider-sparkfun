"""The boards this provider supports, by the ``type`` a config names them with."""

from __future__ import annotations

from .base import DeviceDriver
from .bme280 import BME280
from .scd4x import SCD4x
from .scmd import SCMD

KINDS: dict[str, type[DeviceDriver]] = {
    "bme280": BME280,
    "scd4x": SCD4x,
    "scmd": SCMD,
}

__all__ = ["KINDS", "DeviceDriver"]
