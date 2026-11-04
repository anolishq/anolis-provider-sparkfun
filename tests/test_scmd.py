"""The SCMD board through the provider, in mock mode: the safe state, the
throttle mapping, read-back, and the board's watchdog."""

from __future__ import annotations

from typing import Any

import pytest
import qwiic_scmd
from anolis_provider_sdk import Category, DeviceState, ProviderError, ValueType

from anolis_provider_sparkfun.devices.scmd import (
    SCMD,
    STOP,
    drive_args,
    register_from_throttle,
    throttle_from_register,
)
from anolis_provider_sparkfun.mock import FakeQwiicBus, FakeSCMD, RegisterChip
from anolis_provider_sparkfun.provider import SparkFunProvider

ADDRESS = 0x5D


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def started(**options: Any) -> tuple[SparkFunProvider, FakeSCMD, Clock]:
    p = SparkFunProvider({"mock": True, "devices": [{"id": "drive0", "type": "scmd", **options}]})
    p.start(0.0)
    bus = p._bus
    assert isinstance(bus, FakeQwiicBus)
    chip = bus.chips[ADDRESS]
    assert isinstance(chip, FakeSCMD)
    clock = Clock()
    chip.clock = clock
    chip._fed = clock.now
    return p, chip, clock


def call(p: SparkFunProvider, name: str, throttle: float) -> None:
    d = p.devices()[0]
    fn = d.type.function_by_name(name)
    assert fn
    p.call(d, fn, {"throttle": throttle})


def read(p: SparkFunProvider, *signals: str) -> dict[str, Any]:
    return dict(p.read(p.devices()[0], list(signals)))


def test_the_board_is_stopped_armed_and_enabled_at_connect() -> None:
    _, chip, _ = started()
    r = chip.registers
    assert (r[FakeSCMD.MA_DRIVE], r[FakeSCMD.MB_DRIVE]) == (STOP, STOP)
    assert r[FakeSCMD.FSAFE_TIME] == 200
    assert r[FakeSCMD.DRIVER_ENABLE] == 1


def test_connect_stops_the_motors_and_arms_the_watchdog_before_enabling() -> None:
    chip = FakeSCMD()
    chip.registers[FakeSCMD.MA_DRIVE] = 0xF0  # left running by an earlier session
    writes: list[tuple[int, int]] = []
    bus = FakeQwiicBus({ADDRESS: chip})
    original = bus.writeByte

    def record(address: int, register: int, value: int) -> None:
        writes.append((register, value))
        original(address, register, value)

    bus.writeByte = record  # type: ignore[method-assign,assignment]
    SCMD(bus, ADDRESS, {"failsafe_ms": 1000})
    enable = writes.index((FakeSCMD.DRIVER_ENABLE, 1))
    assert writes.index((FakeSCMD.MA_DRIVE, STOP)) < enable
    assert writes.index((FakeSCMD.MB_DRIVE, STOP)) < enable
    assert writes.index((FakeSCMD.FSAFE_TIME, 100)) < enable


@pytest.mark.parametrize(
    ("throttle", "register"),
    [(0.0, 0x80), (1.0, 0xFF), (-1.0, 0x01), (0.5, 0x80 + 64), (-0.5, 0x80 - 64), (1 / 127, 0x81), (-1 / 127, 0x7F)],
)
def test_throttle_maps_onto_the_firmware_scale(throttle: float, register: int) -> None:
    assert register_from_throttle(throttle) == register
    assert throttle_from_register(register) == pytest.approx(throttle, abs=1 / 254)  # 7 bits a side


def test_a_register_only_another_master_writes_reads_as_full_reverse() -> None:
    assert throttle_from_register(0x00) == -1.0


@pytest.mark.parametrize("register", range(1, 256))
def test_every_register_value_is_reached_exactly_through_the_driver(register: int) -> None:
    chip = FakeSCMD()
    driver = qwiic_scmd.QwiicScmd(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: chip}))
    driver.set_drive(1, *drive_args(register))
    assert chip.registers[FakeSCMD.MB_DRIVE] == register


@pytest.mark.parametrize(
    ("name", "register", "other"),
    [
        ("set_motor_a_throttle", FakeSCMD.MA_DRIVE, FakeSCMD.MB_DRIVE),
        ("set_motor_b_throttle", FakeSCMD.MB_DRIVE, FakeSCMD.MA_DRIVE),
    ],
)
def test_each_function_drives_only_its_own_channel(name: str, register: int, other: int) -> None:
    p, chip, _ = started()
    call(p, name, 1.0)
    assert chip.registers[register] == 0xFF
    assert chip.registers[other] == STOP


def test_the_driver_full_forward_bug_does_not_reach_the_board() -> None:
    p, chip, _ = started()
    call(p, "set_motor_a_throttle", 1.0)
    assert read(p, "motor_a_throttle") == {"motor_a_throttle": 1.0}


def test_throttle_is_read_back_from_the_board() -> None:
    p, chip, _ = started()
    call(p, "set_motor_a_throttle", 0.6)
    call(p, "set_motor_b_throttle", -0.4)
    assert read(p, "motor_a_throttle", "motor_b_throttle") == {
        "motor_a_throttle": pytest.approx(0.6, abs=1 / 254),
        "motor_b_throttle": pytest.approx(-0.4, abs=1 / 254),
    }
    chip.registers[FakeSCMD.MA_DRIVE] = 0x10  # behind the provider's back
    assert read(p, "motor_a_throttle")["motor_a_throttle"] == pytest.approx((0x10 - 0x80) / 127, abs=1e-4)


def test_every_actuating_function_can_be_driven_safe_by_the_zero_rung() -> None:
    # The runtime's zero rung calls each ACTUATE function with its required numeric
    # arguments at 0, and fails the safe state for any it cannot.
    for fn in SCMD.type.functions:
        assert fn.category is Category.ACTUATE
        numeric = [a for a in fn.args if a.type in (ValueType.DOUBLE, ValueType.INT64)]
        assert numeric and all(a.min is not None and a.min <= 0 <= (a.max or 0) for a in numeric)


def test_zero_on_every_function_stops_both_motors() -> None:
    p, chip, _ = started()
    call(p, "set_motor_a_throttle", 0.7)
    call(p, "set_motor_b_throttle", -0.7)
    for fn in SCMD.type.functions:
        call(p, fn.name, 0.0)
    assert read(p, "motor_a_throttle", "motor_b_throttle") == {"motor_a_throttle": 0.0, "motor_b_throttle": 0.0}


def test_polling_keeps_the_watchdog_fed() -> None:
    p, chip, clock = started()
    call(p, "set_motor_a_throttle", 0.5)
    for _ in range(20):  # 10 s at the runtime's default 500 ms
        clock.now += 0.5
        assert read(p, "motor_a_throttle")["motor_a_throttle"] == pytest.approx(0.5, abs=1 / 254)
    assert read(p, "failsafe_trips") == {"failsafe_trips": 0}


def test_when_polling_stops_the_board_stops_the_motors() -> None:
    p, chip, clock = started(failsafe_ms=1000)
    call(p, "set_motor_a_throttle", 0.5)
    call(p, "set_motor_b_throttle", -0.5)
    clock.now += 1.01  # the runtime or the provider stopped
    assert (chip.registers[FakeSCMD.MA_DRIVE], chip.registers[FakeSCMD.MB_DRIVE]) != (STOP, STOP)  # not yet observed
    assert read(p, "motor_a_throttle", "motor_b_throttle", "failsafe_trips") == {
        "motor_a_throttle": 0.0,
        "motor_b_throttle": 0.0,
        "failsafe_trips": 1,
    }


def test_with_the_watchdog_off_the_motors_hold() -> None:
    p, chip, clock = started(failsafe_ms=0)
    assert chip.registers[FakeSCMD.FSAFE_TIME] == 0
    call(p, "set_motor_a_throttle", 0.5)
    clock.now += 60
    assert read(p, "motor_a_throttle")["motor_a_throttle"] == pytest.approx(0.5, abs=1 / 254)


@pytest.mark.parametrize("failsafe_ms", [0, 2000])
def test_a_board_that_restarted_on_its_own_is_made_safe_again(failsafe_ms: int) -> None:
    p, chip, _ = started(failsafe_ms=failsafe_ms)
    chip.power_cycle()
    chip.registers[FakeSCMD.MA_DRIVE] = 0x90  # as if something drove it before the provider looked
    assert read(p, "motor_a_throttle") == {"motor_a_throttle": 0.0}
    assert chip.registers[FakeSCMD.DRIVER_ENABLE] == 1
    assert chip.registers[FakeSCMD.FSAFE_TIME] == failsafe_ms // 10
    call(p, "set_motor_a_throttle", 0.5)
    assert chip.registers[FakeSCMD.MA_DRIVE] == 0x80 + 64


def test_a_board_that_comes_back_after_being_lost_is_stopped() -> None:
    p, chip, _ = started()
    call(p, "set_motor_a_throttle", 0.5)
    bus = p._bus
    assert isinstance(bus, FakeQwiicBus)
    bus.fail = True
    with pytest.raises(ProviderError):
        read(p, "motor_a_throttle")
    bus.fail = False
    chip.registers[FakeSCMD.MA_DRIVE] = 0x90
    assert read(p, "motor_a_throttle") == {"motor_a_throttle": 0.0}


def test_another_chip_at_the_address_is_not_taken_for_an_scmd() -> None:
    with pytest.raises(ValueError, match="ID register"):
        SCMD(FakeQwiicBus({ADDRESS: RegisterChip()}), ADDRESS, {})


def test_a_board_that_never_finishes_starting_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anolis_provider_sparkfun.devices.scmd.ENUMERATION_TIMEOUT_S", 0.05)
    chip = FakeSCMD()
    chip.registers[FakeSCMD.STATUS_1] = 0x00
    with pytest.raises(RuntimeError, match="starting up"):
        SCMD(FakeQwiicBus({ADDRESS: chip}), ADDRESS, {})
    p = SparkFunProvider({"mock": True, "devices": [{"id": "drive0", "type": "scmd"}]})
    with monkeypatch.context() as mp:
        mp.setattr(SCMD, "fake", staticmethod(lambda: chip))
        p.start(0.0)
    health = p.device_health(p.devices()[0])
    assert health and health.state is DeviceState.UNREACHABLE


def test_addresses_are_the_firmwares_with_the_factory_default_first() -> None:
    assert SCMD.addresses[0] == 0x5D
    assert sorted(SCMD.addresses) == list(range(0x58, 0x62))
    assert set(qwiic_scmd.QwiicScmd.available_addresses) <= set(SCMD.addresses)


def test_connect_waits_for_the_board_to_finish_starting() -> None:
    class Starting(FakeSCMD):
        polls = 0

        def read(self, length: int) -> bytes:
            if self._pointer == FakeSCMD.STATUS_1:
                self.polls += 1
                self.registers[FakeSCMD.STATUS_1] = 0x01 if self.polls > 2 else 0x00
            return super().read(length)

    chip = Starting()
    SCMD(FakeQwiicBus({ADDRESS: chip}), ADDRESS, {})
    assert chip.polls == 3
    assert chip.registers[FakeSCMD.DRIVER_ENABLE] == 1
