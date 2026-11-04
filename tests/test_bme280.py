"""The BME280 through the provider, in mock mode: readings, the chips it
refuses, and recovery from a chip that restarted on its own."""

from __future__ import annotations

from typing import Any

import pytest
import qwiic_bme280
from anolis_provider_sdk import DeviceState

from anolis_provider_sparkfun.devices.bme280 import BME280
from anolis_provider_sparkfun.mock import FakeBME280, FakeQwiicBus, RegisterChip
from anolis_provider_sparkfun.provider import SparkFunProvider

ADDRESS = 0x77
SIGNALS = ["temperature", "relative_humidity", "pressure"]


def started(chip: FakeBME280 | None = None) -> tuple[SparkFunProvider, FakeBME280]:
    p = SparkFunProvider({"mock": True, "devices": [{"id": "env0", "type": "bme280"}]})
    p.start(0.0)
    bus = p._bus
    assert isinstance(bus, FakeQwiicBus)
    if chip is not None:
        bus.chips[ADDRESS] = chip
        p._slots["env0"].driver = None  # connect again, to the chip given
    found = bus.chips[ADDRESS]
    assert isinstance(found, FakeBME280)
    return p, found


def read(p: SparkFunProvider, *signals: str) -> dict[str, Any]:
    return dict(p.read(p.devices()[0], list(signals)))


def call(p: SparkFunProvider, name: str, **args: Any) -> None:
    d = p.devices()[0]
    fn = d.type.function_by_name(name)
    assert fn
    p.call(d, fn, args)


def test_readings_are_the_datasheet_worked_example() -> None:
    p, _ = started()
    r = read(p, *SIGNALS)
    assert r["temperature"] == pytest.approx(25.08, abs=0.005)
    assert r["pressure"] == pytest.approx(1006.53, abs=0.005)
    assert r["relative_humidity"] == pytest.approx(43.86, abs=0.01)


def test_altitude_follows_the_sea_level_pressure() -> None:
    p, _ = started()
    assert read(p, "sea_level_pressure") == {"sea_level_pressure": 1013.25}
    assert read(p, "altitude")["altitude"] == pytest.approx(56.07, abs=0.01)
    pressure = read(p, "pressure")["pressure"]
    call(p, "set_sea_level_pressure", sea_level_pressure=pressure)
    assert read(p, "altitude")["altitude"] == pytest.approx(0.0, abs=1e-6)
    assert read(p, "sea_level_pressure")["sea_level_pressure"] == pressure


def test_the_driver_takes_a_bmp280_for_a_bme280() -> None:
    # Why the board checks the chip id itself.
    driver = qwiic_bme280.QwiicBme280(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: FakeBME280(chip_id=0x58)}))
    assert driver.begin() is True


def test_a_bmp280_is_refused_and_reported_unreachable() -> None:
    with pytest.raises(ValueError, match="BMP280"):
        BME280(FakeQwiicBus({ADDRESS: FakeBME280(chip_id=0x58)}), ADDRESS, {})
    p, _ = started(FakeBME280(chip_id=0x58))
    with pytest.raises(Exception, match="BMP280"):
        read(p, "temperature")
    health = p.device_health(p.devices()[0])
    assert health and health.state is DeviceState.UNREACHABLE


def test_another_chip_at_the_address_is_refused() -> None:
    with pytest.raises(ValueError, match="chip id 0x00"):
        BME280(FakeQwiicBus({ADDRESS: RegisterChip()}), ADDRESS, {})


def test_a_chip_that_never_finishes_starting_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anolis_provider_sparkfun.devices.bme280.STARTUP_TIMEOUT_S", 0.01)

    class Stuck(FakeBME280):
        def read(self, length: int) -> bytes:
            if self._pointer == FakeBME280.STATUS:
                return b"\x01"
            return super().read(length)

    with pytest.raises(RuntimeError, match="starting up"):
        BME280(FakeQwiicBus({ADDRESS: Stuck()}), ADDRESS, {})


def test_a_restarted_chip_unattended_reads_plausible_wrong_values() -> None:
    # What the restart check guards against: no error, just wrong numbers.
    chip = FakeBME280()
    driver = qwiic_bme280.QwiicBme280(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: chip}))
    assert driver.begin()
    assert driver.get_temperature_celsius() == pytest.approx(25.08, abs=0.005)
    chip.power_cycle()
    stale = driver.get_temperature_celsius()
    assert stale != pytest.approx(25.08, abs=0.5)
    assert -40 < stale < 85  # inside the sensor's range: nothing looks wrong


def test_a_chip_that_restarted_on_its_own_is_set_up_again() -> None:
    p, chip = started()
    before = read(p, *SIGNALS)
    chip.power_cycle()
    assert read(p, *SIGNALS) == before
    assert chip.registers[FakeBME280.CTRL_MEAS] & 0b11 == qwiic_bme280.QwiicBme280.MODE_NORMAL


def test_new_readings_come_through() -> None:
    p, chip = started()
    t0 = read(p, "temperature")["temperature"]
    chip.set_raw(temperature=530000, pressure=415148, humidity=28000)
    assert read(p, "temperature")["temperature"] > t0


def test_soft_reset_sets_the_chip_up_again_and_keeps_the_sea_level_pressure() -> None:
    p, chip = started()
    call(p, "set_sea_level_pressure", sea_level_pressure=1000.0)
    before = read(p, *SIGNALS)
    call(p, "soft_reset")
    assert chip.registers[FakeBME280.CTRL_MEAS] & 0b11 == qwiic_bme280.QwiicBme280.MODE_NORMAL
    assert read(p, *SIGNALS) == before
    assert read(p, "sea_level_pressure") == {"sea_level_pressure": 1000.0}


def test_a_board_that_comes_back_after_being_lost_reads_again() -> None:
    p, _ = started()
    bus = p._bus
    assert isinstance(bus, FakeQwiicBus)
    bus.fail = True
    with pytest.raises(Exception, match="stopped answering"):
        read(p, "temperature")
    bus.fail = False
    assert read(p, "temperature")["temperature"] == pytest.approx(25.08, abs=0.005)


def test_addresses_are_the_drivers_with_the_factory_default_first() -> None:
    assert BME280.addresses == tuple(qwiic_bme280.QwiicBme280.available_addresses)
