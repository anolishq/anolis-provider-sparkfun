"""The boards this provider supports, by the ``type`` a config names them with."""

from __future__ import annotations

from .base import DeviceDriver
from .scmd import SCMD

KINDS: dict[str, type[DeviceDriver]] = {
    "scmd": SCMD,
}

__all__ = ["KINDS", "DeviceDriver"]
