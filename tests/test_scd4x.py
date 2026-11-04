"""The SCD4x board against the sensor model, on a stepped clock: the 5 s
measurement cycle, the first-measurement gap, the chips it refuses, and
recovery from a sensor that restarted on its own."""

from __future__ import annotations

import math
import types
from typing import Any

import pytest
import qwiic_scd4x
from anolis_provider_sdk import Quality, Reading

from anolis_provider_sparkfun.devices import scd4x as board
from anolis_provider_sparkfun.devices.base import NotAnswering
from anolis_provider_sparkfun.devices.scd4x import SCD4x
from anolis_provider_sparkfun.mock import FakeQwiicBus, FakeSCD4x

ADDRESS = 0x62
SIGNALS = ["co2", "temperature", "relative_humidity"]


class Clock:
    """Monotonic and wall time that move only when slept or stepped."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def wall(self) -> float:
        return 1_800_000_000.0 + self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    fake_time = types.SimpleNamespace(monotonic=c, time=c.wall, sleep=c.sleep)
    monkeypatch.setattr(qwiic_scd4x, "time", fake_time)
    monkeypatch.setattr(board, "time", fake_time)
    return c


def connected(clock: Clock, chip: FakeSCD4x | None = None) -> tuple[SCD4x, FakeSCD4x]:
    chip = chip or FakeSCD4x(clock)
    return SCD4x(FakeQwiicBus({ADDRESS: chip}), ADDRESS, {}), chip


def values(readings: Any) -> dict[str, float]:
    return {sid: r.value for sid, r in readings.items()}


def test_before_the_first_measurement_every_signal_is_nan_and_unknown(clock: Clock) -> None:
    s, _ = connected(clock)
    readings = s.read(SIGNALS)
    for r in readings.values():
        assert isinstance(r, Reading)
        assert math.isnan(r.value) and r.quality is Quality.UNKNOWN


def test_the_first_measurement_arrives_after_one_period(clock: Clock) -> None:
    s, _ = connected(clock)
    clock.sleep(5.0)
    readings = s.read(SIGNALS)
    assert values(readings) == {
        "co2": 600.0,
        "temperature": pytest.approx(22.5, abs=175 / 65536),
        "relative_humidity": pytest.approx(40.0, abs=100 / 65536),
    }
    assert all(r.quality is Quality.OK and r.timestamp == clock.wall() for r in readings.values())


def test_between_measurements_the_latest_is_returned_with_its_fetch_time(clock: Clock) -> None:
    s, chip = connected(clock)
    clock.sleep(5.0)
    first = s.read(["co2"])["co2"]
    chip.set_measurement(co2=900, temperature=25.0, humidity=50.0)
    clock.sleep(2.0)
    again = s.read(["co2"])["co2"]
    assert first.timestamp is not None
    assert (again.value, again.timestamp) == (first.value, first.timestamp)
    clock.sleep(3.0)
    assert s.read(["co2"])["co2"].value == 900.0


def test_the_driver_begin_reports_success_for_a_chip_whose_serial_fails_its_crc(clock: Clock) -> None:
    # Why the board checks the serial number itself.
    driver = qwiic_scd4x.QwiicSCD4x(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: Garbled(clock)}))
    assert driver.begin(measBegin=False) is True
    assert driver.get_serial_number() is None


class Garbled(FakeSCD4x):
    """Something at 0x62 that is not an intact SCD4x: its replies fail the CRC."""

    def read(self, length: int) -> bytes:
        return bytes(b ^ 0x01 for b in super().read(length))


def test_a_chip_whose_serial_fails_its_crc_is_refused(clock: Clock) -> None:
    with pytest.raises(NotAnswering, match="serial number"):
        connected(clock, Garbled(clock))


def test_the_sensor_is_started_and_self_calibration_is_on(clock: Clock) -> None:
    chip = FakeSCD4x(clock)
    chip.asc = False
    connected(clock, chip)
    assert chip.periodic and chip.asc


def test_a_sensor_left_measuring_by_an_earlier_session_is_taken_over(clock: Clock) -> None:
    chip = FakeSCD4x(clock)
    chip.write(FakeSCD4x.START_PERIODIC.to_bytes(2, "big"))  # commands other than stop are refused now
    s, _ = connected(clock, chip)
    clock.sleep(5.0)
    assert s.read(["co2"])["co2"].value == 600.0


def test_a_sensor_that_restarted_on_its_own_is_started_again(clock: Clock) -> None:
    s, chip = connected(clock)
    clock.sleep(5.0)
    assert s.read(["co2"])["co2"].quality is Quality.OK
    chip.power_cycle()  # idle: no more measurements
    chip.set_measurement(co2=750, temperature=22.5, humidity=40.0)
    for _ in range(4):  # 20 s at one read every 5 s
        clock.sleep(5.0)
        s.read(["co2"])
    assert chip.periodic
    clock.sleep(5.0)
    assert s.read(["co2"])["co2"].value == 750.0


def test_a_measuring_sensor_is_not_restarted(clock: Clock) -> None:
    s, chip = connected(clock)
    started = chip._started
    for _ in range(100):  # 50 s at the runtime's default 500 ms polling
        clock.sleep(0.5)
        s.read(["co2"])
    assert chip._started == started


def test_ambient_pressure_is_applied_and_reapplied_after_a_restart(clock: Clock) -> None:
    s, chip = connected(clock)
    fn = SCD4x.type.function_by_name("set_ambient_pressure")
    assert fn
    s.call(fn, {"pressure": 1006.5})
    assert chip.ambient_pressure_hpa == 1006
    chip.power_cycle()
    for _ in range(4):
        clock.sleep(5.0)
        s.read(["co2"])
    assert chip.ambient_pressure_hpa == 1006


def test_the_provider_lists_it_and_reads_it_in_mock_mode() -> None:
    from anolis_provider_sparkfun.provider import SparkFunProvider

    p = SparkFunProvider({"mock": True, "devices": [{"id": "air0", "type": "scd4x"}]})
    p.start(0.0)
    assert p.device_health(p.devices()[0]) is None
    assert set(p.read(p.devices()[0], SIGNALS)) == set(SIGNALS)


def test_ambient_pressure_survives_a_reconnect(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    from anolis_provider_sdk import ProviderError

    from anolis_provider_sparkfun.provider import SparkFunProvider

    chip = FakeSCD4x(clock)
    monkeypatch.setattr(SCD4x, "fake", staticmethod(lambda: chip))
    p = SparkFunProvider({"mock": True, "devices": [{"id": "air0", "type": "scd4x"}]})
    p.start(0.0)
    d = p.devices()[0]
    fn = SCD4x.type.function_by_name("set_ambient_pressure")
    assert fn
    p.call(d, fn, {"pressure": 1006.5})
    bus = p._bus
    assert isinstance(bus, FakeQwiicBus)
    bus.fail = True  # the cable is out, and the sensor loses power with it
    with pytest.raises(ProviderError):
        p.read(d, ["co2"])
    chip.power_cycle()
    bus.fail = False
    clock.sleep(5.0)
    p.read(d, ["co2"])
    assert chip.ambient_pressure_hpa == 1006
