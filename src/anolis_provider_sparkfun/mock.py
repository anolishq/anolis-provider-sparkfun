"""A fake I2C bus for mock mode, CI and tests.

It implements the bus interface the SparkFun drivers call (qwiic_i2c's
I2CDriver: readByte, writeByte, readBlock and the rest, as LinuxI2C maps them
onto SMBus transfers) and puts a register model of each chip behind it. The real
drivers run unchanged against it, so mock mode exercises the same driver code as
the hardware does, from the first register read on.
"""

from __future__ import annotations

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
            if data[0] == self.FSAFE_TIME:
                self._fed = self.clock()

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
