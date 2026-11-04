"""qwiic_sht4x: Sensirion SHT40, SHT41 and SHT45 temperature and humidity.

Staged for upstream: see this package's docstring.

From the Sensirion SHT4x datasheet: one-byte commands; a
measurement replies with a temperature word and a humidity word, each followed
by a CRC-8 (polynomial 0x31, initial value 0xFF); high precision takes up to
8.3 ms. T = -45 + 175 * raw / 65535 (C), RH = -6 + 125 * raw / 65535 (%),
clipped to 0 to 100. The heater commands are deliberately absent: run for
long, the heater damages the sensor.
"""

from __future__ import annotations

import time
from typing import Any

_DEFAULT_NAME = "Qwiic SHT4x"
# 0x44 is the SHT4x-A variant, the common one; 0x45 and 0x46 are the -B and -C.
_AVAILABLE_I2C_ADDRESS = [0x44, 0x45, 0x46]


def crc8(data: bytes | list[int]) -> int:
    """Sensirion CRC-8 over a 16-bit word: polynomial 0x31, initial 0xFF."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) if crc & 0x80 else crc << 1
    return crc & 0xFF


def _words(data: list[int]) -> list[int] | None:
    """The 16-bit words of a reply, or None if any CRC fails."""
    out = []
    for i in range(0, len(data) - 2, 3):
        if crc8(data[i : i + 2]) != data[i + 2]:
            return None
        out.append((data[i] << 8) | data[i + 1])
    return out


class QwiicSHT4x:
    """An SHT4x on a qwiic_i2c bus."""

    device_name = _DEFAULT_NAME
    available_addresses = _AVAILABLE_I2C_ADDRESS

    MEASURE_HIGH_PRECISION = 0xFD
    READ_SERIAL = 0x89
    SOFT_RESET = 0x94
    MEASURE_TIME_S = 0.010  # 8.3 ms maximum at high precision
    RESET_TIME_S = 0.001

    def __init__(self, address: int | None = None, i2c_driver: Any = None) -> None:
        self.address = address if address is not None else self.available_addresses[0]
        if i2c_driver is None:
            import qwiic_i2c

            i2c_driver = qwiic_i2c.getI2CDriver()
        self._i2c = i2c_driver

    def is_connected(self) -> bool:
        return bool(self._i2c.isDeviceConnected(self.address))

    connected = property(is_connected)

    def begin(self) -> bool:
        """Reset the sensor and check that it answers as an SHT4x: True if its
        serial number reads back with intact CRCs."""
        if not self.is_connected():
            return False
        self.soft_reset()
        return self.get_serial_number() is not None

    def soft_reset(self) -> None:
        self._i2c.writeCommand(self.address, self.SOFT_RESET)
        time.sleep(self.RESET_TIME_S)

    def get_serial_number(self) -> int | None:
        """The 32-bit serial number, or None if the reply fails its CRC."""
        words = self._command(self.READ_SERIAL, 6, 0.001)
        return None if words is None else (words[0] << 16) | words[1]

    def measure(self) -> tuple[float, float] | None:
        """(temperature in C, relative humidity in %), high precision, heater
        off; None if the reply fails its CRC."""
        words = self._command(self.MEASURE_HIGH_PRECISION, 6, self.MEASURE_TIME_S)
        if words is None:
            return None
        temperature = -45.0 + 175.0 * words[0] / 65535.0
        humidity = -6.0 + 125.0 * words[1] / 65535.0
        return temperature, max(0.0, min(100.0, humidity))

    def _command(self, command: int, length: int, wait_s: float) -> list[int] | None:
        self._i2c.writeCommand(self.address, command)
        time.sleep(wait_s)
        return _words(list(self._i2c.readBlock(self.address, None, length)))
