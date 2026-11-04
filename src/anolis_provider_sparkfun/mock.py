"""A fake I2C bus for mock mode, CI and tests.

It implements the bus interface the SparkFun drivers call (qwiic_i2c's
I2CDriver: readByte, writeByte, readBlock and the rest, as LinuxI2C maps them
onto SMBus transfers) and puts a register model of each chip behind it. The real
drivers run unchanged against it, so mock mode exercises the same driver code as
the hardware does, from the first register read on.
"""

from __future__ import annotations

import struct
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol


class FakeChip(Protocol):
    def write(self, data: bytes) -> None:
        """A write transfer, ended with a stop."""

    def select(self, register: int) -> None:
        """The register-pointer half of a combined transfer: a write followed
        by a repeated start, as SMBus reads do."""

    def read(self, length: int) -> bytes: ...


class RegisterChip:
    """A chip with an 8-bit register pointer: a write sets the pointer and
    writes any following bytes from it; a read returns bytes from the pointer.
    The pointer advances with each byte, as on most I2C register chips."""

    def __init__(self) -> None:
        self.registers = bytearray(256)
        self._pointer = 0

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._pointer = data[0]
        for byte in data[1:]:
            self.on_write(self._pointer, byte)
            self._pointer = self.next_register(self._pointer)

    def select(self, register: int) -> None:
        self._pointer = register

    def read(self, length: int) -> bytes:
        out = bytearray()
        for _ in range(length):
            out.append(self.registers[self._pointer])
            self._pointer = self.next_register(self._pointer)
        return bytes(out)

    def next_register(self, register: int) -> int:
        """Where the pointer goes after a byte is transferred."""
        return (register + 1) & 0xFF

    def on_write(self, register: int, value: int) -> None:
        self.registers[register] = value


class FakeBME280(RegisterChip):
    """A Bosch BME280 holding the calibration and raw readings of the datasheet's
    worked example (BST-BME280-DS002, section 8.1): 25.08 C and 1006.53 hPa
    through the compensation. The humidity calibration is a typical part's,
    giving about 45 %.

    Modelled because a driver or the provider can get each of them wrong:

    - Power-on (and a soft reset, 0xB6 to 0xE0) leaves the chip in sleep mode
      with every setting 0, and the data registers at their reset values,
      0x80000 for temperature and pressure and 0x8000 for humidity. Those
      convert to plausible-looking numbers, so a restarted chip that nobody
      reconfigures reads wrong rather than failing.
    - A measurement runs only outside sleep mode and only for a quantity whose
      oversampling is not 0 ("skipped"); a skipped one keeps reading its reset
      value. The humidity setting in ctrl_hum takes effect at the next write to
      ctrl_meas (datasheet 5.4.3).
    - ``chip_id`` 0x58 makes it a BMP280, which has no humidity.

    The model measures instantly: a read outside sleep mode returns the latest
    raw values set with ``set_raw``.
    """

    CHIP_ID_REG, RESET_REG = 0xD0, 0xE0
    CTRL_HUM, STATUS, CTRL_MEAS, CONFIG = 0xF2, 0xF3, 0xF4, 0xF5
    DATA = 0xF7  # press_msb .. hum_lsb, 0xF7 to 0xFE
    CHIP_ID = 0x60
    SKIPPED_TP, SKIPPED_H = 0x80000, 0x8000

    def __init__(self, chip_id: int = CHIP_ID) -> None:
        super().__init__()
        self.chip_id = chip_id
        self.raw = {"temperature": 519888, "pressure": 415148, "humidity": 28000}
        self.power_cycle()

    def power_cycle(self) -> None:
        """Every register at its power-on value, as at start-up, after a soft
        reset, or after a brown-out."""
        r = self.registers
        r[:] = bytes(256)
        r[self.CHIP_ID_REG] = self.chip_id
        # dig_T1..T3, dig_P1..P9 from 0x88, little-endian.
        r[0x88:0xA0] = struct.pack(
            "<HhhHhhhhhhhh", 27504, 26435, -1000, 36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000
        )
        r[0xA1] = 75  # dig_H1
        # dig_H2 = 362, dig_H3 = 0, dig_H4 = 313, dig_H5 = 50, dig_H6 = 30, packed as the chip packs them.
        r[0xE1:0xE8] = struct.pack("<hBbBbb", 362, 0, 313 >> 4, ((50 & 0xF) << 4) | (313 & 0xF), 50 >> 4, 30)
        self._humidity_on = False
        self._store(self.SKIPPED_TP, self.SKIPPED_TP, self.SKIPPED_H)

    def set_raw(self, *, temperature: int, pressure: int, humidity: int) -> None:
        """Raw ADC values the next measurement returns: 20-bit temperature and
        pressure, 16-bit humidity."""
        self.raw = {"temperature": temperature, "pressure": pressure, "humidity": humidity}

    def _store(self, temperature: int, pressure: int, humidity: int) -> None:
        self.registers[0xF7:0xFA] = (pressure << 4).to_bytes(3, "big")
        self.registers[0xFA:0xFD] = (temperature << 4).to_bytes(3, "big")
        self.registers[0xFD:0xFF] = humidity.to_bytes(2, "big")

    def _measure(self) -> None:
        meas = self.registers[self.CTRL_MEAS]
        if meas & 0b11 == 0:  # sleep: the data registers hold their last values
            return
        r = self.raw
        self._store(
            r["temperature"] if meas >> 5 else self.SKIPPED_TP,
            r["pressure"] if (meas >> 2) & 0b111 else self.SKIPPED_TP,
            r["humidity"] if self._humidity_on and self.chip_id == self.CHIP_ID else self.SKIPPED_H,
        )

    def on_write(self, register: int, value: int) -> None:
        if register == self.RESET_REG:
            if value == 0xB6:
                self.power_cycle()
            return
        if register not in (self.CTRL_HUM, self.CTRL_MEAS, self.CONFIG):
            return  # the id, the status, the data and the calibration are read-only
        super().on_write(register, value)
        if register == self.CTRL_MEAS:
            self._humidity_on = bool(self.registers[self.CTRL_HUM] & 0b111)

    def read(self, length: int) -> bytes:
        if self._pointer == self.DATA or self._pointer in (0xFA, 0xFD):
            self._measure()
        return super().read(length)


class FakeSCMD(RegisterChip):
    """The SparkFun Serial Controlled Motor Driver (SCMD) firmware, as the
    Qwiic Motor Driver runs it: the user-port register map, at the values the
    firmware sets at power-on (SCMD_FW devRegisters.c, setColdInitValues), on a
    board with no expansion-port slaves.

    Modelled because a driver or the provider can get each of them wrong:

    - The firmware takes one register per write. A one-byte write only moves
      the pointer, two bytes write one register, and anything longer is dropped
      and counted in U_BUF_DUMPED (customSerialInterrupts.c, parseI2C). A read
      returns the register at the pointer.
    - ID, FID, CONFIG_BITS and STATUS_1 are read-only; a write to one is
      dropped and counted in REG_RO_WRITE_CNT.
    - The failsafe watchdog: with FSAFE_TIME set to n, a gap of n x 10 ms with
      no completed write sets both drive registers to 0x80 (stop) and counts a
      fault in FSAFE_FAULTS, once per expired period (main.c,
      FSAFE_TIMER_Interrupt; FSAFE_CTRL's power-on value has DRIVE_KILL set).
      Every write that ends with a stop restarts it, a pointer-only one
      included. Whether the pointer write inside an SMBus read (ended by a
      repeated start) restarts it is not settled from the firmware source, so
      the model assumes it does not.

    ``clock`` is in seconds; tests pass their own to step time.
    """

    ID, FID, CONFIG_BITS = 0x01, 0x00, 0x03
    U_BUF_DUMPED, FSAFE_FAULTS, REG_RO_WRITE_CNT = 0x06, 0x0E, 0x10
    FSAFE_CTRL, MA_DRIVE, MB_DRIVE = 0x1F, 0x20, 0x21
    DRIVER_ENABLE, FSAFE_TIME, STATUS_1 = 0x70, 0x76, 0x77

    ID_WORD = 0xA9
    STOP = 0x80
    DRIVE_KILL = 0x01
    _READ_ONLY = frozenset({ID, FID, CONFIG_BITS, STATUS_1})

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__()
        self.clock = clock
        self.power_cycle()

    def power_cycle(self) -> None:
        """Every register at its power-on value, as at start-up or after the
        board restarts on a brown-out."""
        r = self.registers
        r[:] = bytes(256)
        r[self.FID] = 0x07  # firmware version 7, the current release
        r[self.ID] = self.ID_WORD
        r[self.CONFIG_BITS] = 0x08  # the factory jumpers: I2C at 0x5D
        r[self.FSAFE_CTRL] = 0x19  # re-init both ports, stop the motors
        r[self.MA_DRIVE] = r[self.MB_DRIVE] = self.STOP
        r[self.DRIVER_ENABLE] = 0x00
        r[self.FSAFE_TIME] = 0x00  # watchdog off
        r[self.STATUS_1] = 0x01  # enumeration complete
        self._fed = self.clock()

    def _tick(self) -> None:
        period = self.registers[self.FSAFE_TIME] * 0.010
        now = self.clock()
        if not period or now - self._fed < period:
            return
        expired = int((now - self._fed) // period)
        self._fed += expired * period
        self.registers[self.FSAFE_FAULTS] = min(0xFF, self.registers[self.FSAFE_FAULTS] + expired)
        if self.registers[self.FSAFE_CTRL] & self.DRIVE_KILL:
            self.registers[self.MA_DRIVE] = self.registers[self.MB_DRIVE] = self.STOP

    def write(self, data: bytes) -> None:
        self._tick()
        if not data:
            return
        self._fed = self.clock()
        if len(data) > 2:
            self.registers[self.U_BUF_DUMPED] = min(0xFF, self.registers[self.U_BUF_DUMPED] + 1)
            return
        self._pointer = data[0]
        if len(data) == 2:
            if data[0] in self._READ_ONLY:
                self.registers[self.REG_RO_WRITE_CNT] = min(0xFF, self.registers[self.REG_RO_WRITE_CNT] + 1)
                return
            self.registers[data[0]] = data[1]

    def select(self, register: int) -> None:
        self._tick()
        self._pointer = register

    def read(self, length: int) -> bytes:
        self._tick()
        # The firmware stages one byte per read (bufferTx[0]); more is not modelled.
        if length != 1:
            raise NotImplementedError("the SCMD returns one register per read")
        return bytes([self.registers[self._pointer]])


class FakeQwiicBus:
    """A bus with fake chips at fixed addresses, with qwiic_i2c's I2CDriver
    methods mapped onto chip transfers as LinuxI2C maps them onto SMBus calls.
    An address with no chip raises OSError, as Linux reports a NACK, so a
    driver's probe fails as on hardware. Byte values are truncated to 8 bits,
    as smbus2 does when it packs them."""

    def __init__(self, chips: Mapping[int, FakeChip]) -> None:
        self.chips = dict(chips)
        self.fail = False  # set to make every transfer fail, as a disconnected bus does

    def _chip(self, address: int) -> FakeChip:
        if self.fail:
            raise OSError(5, "Input/output error")
        chip = self.chips.get(address)
        if chip is None:
            raise OSError(121, "Remote I/O error")
        return chip

    def readByte(self, address: int, commandCode: int | None = None) -> int:
        chip = self._chip(address)
        if commandCode is not None:
            chip.select(commandCode & 0xFF)
        return chip.read(1)[0]

    def readWord(self, address: int, commandCode: int) -> int:
        chip = self._chip(address)
        chip.select(commandCode & 0xFF)
        return int.from_bytes(chip.read(2), "little")

    def readBlock(self, address: int, commandCode: int | None, nBytes: int) -> list[int]:
        chip = self._chip(address)
        if commandCode is not None:
            chip.select(commandCode & 0xFF)
        return list(chip.read(nBytes))

    def writeCommand(self, address: int, commandCode: int) -> None:
        self._chip(address).write(bytes([commandCode & 0xFF]))

    def writeByte(self, address: int, commandCode: int, value: int) -> None:
        self._chip(address).write(bytes([commandCode & 0xFF, value & 0xFF]))

    def writeWord(self, address: int, commandCode: int, value: int) -> None:
        self._chip(address).write(bytes([commandCode & 0xFF, value & 0xFF, (value >> 8) & 0xFF]))

    def writeBlock(self, address: int, commandCode: int, value: Sequence[int]) -> None:
        self._chip(address).write(bytes([commandCode & 0xFF, *(v & 0xFF for v in value)]))

    def isDeviceConnected(self, devAddress: int) -> bool:
        try:
            self._chip(devAddress)
        except OSError:
            return False
        return True

    # qwiic_i2c names each method in camelCase and in snake_case; drivers use both.
    read_byte = readByte
    read_word = readWord
    read_block = readBlock
    write_command = writeCommand
    write_byte = writeByte
    write_word = writeWord
    write_block = writeBlock
    is_device_connected = isDeviceConnected
