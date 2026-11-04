"""qwiic_shtc3: Sensirion SHTC3 temperature and humidity.

Staged for upstream: see this package's docstring.

From the Sensirion SHTC3 datasheet: 16-bit commands sent MSB
first; replies are 16-bit words each followed by a CRC-8 (polynomial 0x31,
initial value 0xFF). The sensor has a sleep mode in which it acknowledges
only the wake-up command, and needs up to 240 us to wake. A normal-mode
measurement (temperature first, no clock stretching) takes up to 12.1 ms.
T = -45 + 175 * raw / 65536 (C), RH = 100 * raw / 65536 (%). The id register
has bits 11 and 5..0 defined, reading 0x0807 on an SHTC3.

The driver leaves the sensor asleep between measurements, as the datasheet
recommends, and wakes it for each one.
"""

from __future__ import annotations

import time
from typing import Any

from .qwiic_sht4x import _words

_DEFAULT_NAME = "Qwiic SHTC3"
_AVAILABLE_I2C_ADDRESS = [0x70]


class QwiicSHTC3:
    """An SHTC3 on a qwiic_i2c bus."""

    device_name = _DEFAULT_NAME
    available_addresses = _AVAILABLE_I2C_ADDRESS

    WAKEUP = 0x3517
    SLEEP = 0xB098
    SOFT_RESET = 0x805D
    READ_ID = 0xEFC8
    MEASURE_NORMAL_T_FIRST = 0x7866
    ID_MASK, ID = 0x083F, 0x0807
    WAKE_TIME_S = 0.001  # 240 us maximum
    MEASURE_TIME_S = 0.013  # 12.1 ms maximum

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
        """Wake and reset the sensor and check its id: True if it answers as
        an SHTC3. Leaves it asleep.

        Does not probe with is_connected() first: a sleeping SHTC3 may not
        acknowledge an address-only probe, and one left asleep by an earlier
        session must still be found. The wake-up command is what it answers
        asleep; with nothing at the address, it fails as a bus error."""
        self.wake()
        self._send(self.SOFT_RESET)
        time.sleep(self.WAKE_TIME_S)
        chip_id = self.get_id()
        self.sleep()
        return chip_id is not None and chip_id & self.ID_MASK == self.ID

    def wake(self) -> None:
        self._send(self.WAKEUP)
        time.sleep(self.WAKE_TIME_S)

    def sleep(self) -> None:
        self._send(self.SLEEP)

    def get_id(self) -> int | None:
        """The id register, or None if the reply fails its CRC. The sensor
        must be awake."""
        self._send(self.READ_ID)
        words = _words(list(self._i2c.readBlock(self.address, None, 3)))
        return None if words is None else words[0]

    def measure(self) -> tuple[float, float] | None:
        """(temperature in C, relative humidity in %); None if the reply fails
        its CRC. Wakes the sensor for the measurement and puts it back to
        sleep afterwards, whether the CRC passed or not."""
        self.wake()
        self._send(self.MEASURE_NORMAL_T_FIRST)
        time.sleep(self.MEASURE_TIME_S)
        words = _words(list(self._i2c.readBlock(self.address, None, 6)))
        self.sleep()
        if words is None:
            return None
        return -45.0 + 175.0 * words[0] / 65536.0, 100.0 * words[1] / 65536.0

    def _send(self, command: int) -> None:
        self._i2c.writeBlock(self.address, command >> 8, [command & 0xFF])
