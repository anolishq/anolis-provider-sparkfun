"""The fake bus and the SCMD model against SparkFun's real driver and the
firmware's documented behaviour: if the model were wrong, mock mode would test
the provider against a board that does not exist."""

from __future__ import annotations

import pytest
import qwiic_scmd

from anolis_provider_sparkfun.mock import FakeBME280, FakeQwiicBus, FakeSCMD

ADDRESS = 0x5D


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def board(clock: Clock | None = None) -> tuple[FakeSCMD, FakeQwiicBus, qwiic_scmd.QwiicScmd]:
    chip = FakeSCMD(clock or Clock())
    bus = FakeQwiicBus({ADDRESS: chip})
    return chip, bus, qwiic_scmd.QwiicScmd(ADDRESS, i2c_driver=bus)


def test_the_driver_finds_the_board_and_sees_it_ready() -> None:
    _, _, driver = board()
    assert driver.begin() == qwiic_scmd.QwiicScmd.ID_WORD
    assert driver.ready()
    assert not driver.busy()


def test_the_driver_enables_and_drives_through_the_model() -> None:
    chip, _, driver = board()
    driver.enable()
    driver.set_drive(0, 1, 100)
    driver.set_drive(1, 0, 100)
    assert chip.registers[FakeSCMD.DRIVER_ENABLE] == 1
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x80 + 50
    assert chip.registers[FakeSCMD.MB_DRIVE] == 0x80 - 50
    driver.disable()
    assert chip.registers[FakeSCMD.DRIVER_ENABLE] == 0


def test_the_driver_full_forward_goes_out_as_full_reverse() -> None:
    # sparkfun-qwiic-scmd 2.0.0: set_drive(m, 1, 255) computes 0x80 + 128 = 0x100,
    # and smbus2 sends the low byte. The provider never asks for this level.
    chip, _, driver = board()
    driver.set_drive(0, 1, 255)
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x00


def test_power_on_values_match_the_firmware() -> None:
    r = FakeSCMD(Clock()).registers
    assert (r[FakeSCMD.ID], r[FakeSCMD.FID]) == (0xA9, 0x07)
    assert (r[FakeSCMD.MA_DRIVE], r[FakeSCMD.MB_DRIVE]) == (0x80, 0x80)
    assert r[FakeSCMD.DRIVER_ENABLE] == 0
    assert r[FakeSCMD.FSAFE_TIME] == 0
    assert r[FakeSCMD.FSAFE_CTRL] & FakeSCMD.DRIVE_KILL


def test_writes_longer_than_one_register_are_dropped_and_counted() -> None:
    chip, bus, _ = board()
    bus.writeBlock(ADDRESS, FakeSCMD.MA_DRIVE, [0x90, 0x90])
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x80
    assert chip.registers[FakeSCMD.U_BUF_DUMPED] == 1


def test_read_only_registers_refuse_writes() -> None:
    chip, bus, _ = board()
    bus.writeByte(ADDRESS, FakeSCMD.ID, 0x00)
    assert chip.registers[FakeSCMD.ID] == 0xA9
    assert chip.registers[FakeSCMD.REG_RO_WRITE_CNT] == 1


def test_a_missing_board_is_a_remote_io_error() -> None:
    _, bus, _ = board()
    with pytest.raises(OSError) as err:
        bus.readByte(0x58, 0x01)
    assert err.value.errno == 121
    assert not bus.isDeviceConnected(0x58)
    assert bus.isDeviceConnected(ADDRESS)


def test_the_watchdog_stops_both_motors_after_its_timeout() -> None:
    clock = Clock()
    chip, bus, driver = board(clock)
    bus.writeByte(ADDRESS, FakeSCMD.FSAFE_TIME, 50)  # 500 ms
    driver.set_drive(0, 1, 100)
    driver.set_drive(1, 0, 100)
    clock.now += 0.49
    assert bus.readByte(ADDRESS, FakeSCMD.MA_DRIVE) == 0x80 + 50
    clock.now += 0.02
    assert bus.readByte(ADDRESS, FakeSCMD.MA_DRIVE) == 0x80
    assert bus.readByte(ADDRESS, FakeSCMD.MB_DRIVE) == 0x80
    assert bus.readByte(ADDRESS, FakeSCMD.FSAFE_FAULTS) == 1


def test_a_write_feeds_the_watchdog_and_an_smbus_read_does_not() -> None:
    clock = Clock()
    chip, bus, driver = board(clock)
    bus.writeByte(ADDRESS, FakeSCMD.FSAFE_TIME, 50)
    driver.set_drive(0, 1, 100)
    for _ in range(4):
        clock.now += 0.3
        bus.writeCommand(ADDRESS, FakeSCMD.STATUS_1)  # pointer-only write
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x80 + 50
    for _ in range(2):
        clock.now += 0.3
        bus.readByte(ADDRESS, FakeSCMD.STATUS_1)
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x80


def test_the_watchdog_counts_every_expired_period_and_is_off_at_zero() -> None:
    clock = Clock()
    chip, bus, _ = board(clock)
    bus.writeByte(ADDRESS, FakeSCMD.FSAFE_TIME, 10)  # 100 ms
    clock.now += 0.35
    assert bus.readByte(ADDRESS, FakeSCMD.FSAFE_FAULTS) == 3
    bus.writeByte(ADDRESS, FakeSCMD.FSAFE_TIME, 0)
    bus.writeByte(ADDRESS, FakeSCMD.MA_DRIVE, 0x90)
    clock.now += 10
    assert bus.readByte(ADDRESS, FakeSCMD.MA_DRIVE) == 0x90


def test_a_power_cycle_restores_the_power_on_values() -> None:
    chip, bus, driver = board()
    driver.enable()
    bus.writeByte(ADDRESS, FakeSCMD.FSAFE_TIME, 50)
    driver.set_drive(0, 1, 100)
    chip.power_cycle()
    assert chip.registers[FakeSCMD.DRIVER_ENABLE] == 0
    assert chip.registers[FakeSCMD.FSAFE_TIME] == 0
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x80


def test_the_bme280_powers_on_asleep_with_reset_values_in_its_data_registers() -> None:
    chip = FakeBME280()
    bus = FakeQwiicBus({0x77: chip})
    assert bus.readByte(0x77, FakeBME280.CTRL_MEAS) == 0
    assert bus.readBlock(0x77, FakeBME280.DATA, 8) == [0x80, 0, 0, 0x80, 0, 0, 0x80, 0]


def test_the_bme280_humidity_setting_takes_effect_at_the_next_ctrl_meas_write() -> None:
    chip = FakeBME280()
    bus = FakeQwiicBus({0x77: chip})
    bus.writeByte(0x77, FakeBME280.CTRL_HUM, 0x01)
    bus.writeByte(0x77, FakeBME280.CTRL_MEAS, 0b001_001_00)  # temperature and pressure only, still asleep
    bus.writeByte(0x77, FakeBME280.CTRL_MEAS, 0b001_001_11)  # normal mode
    assert int.from_bytes(bytes(bus.readBlock(0x77, 0xFD, 2)), "big") == 28000
    chip.power_cycle()
    bus.writeByte(0x77, FakeBME280.CTRL_MEAS, 0b001_001_11)
    bus.writeByte(0x77, FakeBME280.CTRL_HUM, 0x01)  # after ctrl_meas: not applied yet
    assert int.from_bytes(bytes(bus.readBlock(0x77, 0xFD, 2)), "big") == FakeBME280.SKIPPED_H


def test_the_bme280_soft_reset_restores_power_on_values_and_calibration_is_read_only() -> None:
    chip = FakeBME280()
    bus = FakeQwiicBus({0x77: chip})
    bus.writeByte(0x77, FakeBME280.CTRL_MEAS, 0x27)
    bus.writeByte(0x77, 0x88, 0x00)
    assert chip.registers[0x88] != 0x00
    bus.writeByte(0x77, FakeBME280.RESET_REG, 0xB6)
    assert chip.registers[FakeBME280.CTRL_MEAS] == 0
