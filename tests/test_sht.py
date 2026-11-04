"""The staged SHT4x and SHTC3 drivers against their sensor models, and the
boards built on them through the provider."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from anolis_provider_sdk import DeviceState, ProviderError

import anolis_qwiic_staging
from anolis_provider_sparkfun.devices.sht import SHTC3, SHT4x
from anolis_provider_sparkfun.mock import FakeQwiicBus, FakeSHT4x, FakeSHTC3
from anolis_provider_sparkfun.provider import SparkFunProvider
from anolis_qwiic_staging.qwiic_sht4x import QwiicSHT4x, crc8
from anolis_qwiic_staging.qwiic_shtc3 import QwiicSHTC3

SIGNALS = ["temperature", "relative_humidity"]


class Garbled:
    """Flips a bit in every reply, so each word fails its CRC, while ``on``."""

    on = False

    def read(self, length: int) -> bytes:
        out = super().read(length)  # type: ignore[misc]
        return bytes(b ^ 0x01 for b in out) if self.on else out


class GarbledSHT4x(Garbled, FakeSHT4x):
    pass


class GarbledSHTC3(Garbled, FakeSHTC3):
    pass


# ---- the staged drivers --------------------------------------------------------


def test_crc8_matches_the_datasheet_example() -> None:
    assert crc8(b"\xbe\xef") == 0x92


def test_sht4x_measures_and_reads_its_serial_number() -> None:
    chip = FakeSHT4x()
    chip.set_measurement(temperature=31.25, humidity=62.5)
    sensor = QwiicSHT4x(0x44, i2c_driver=FakeQwiicBus({0x44: chip}))
    assert sensor.begin()
    assert sensor.get_serial_number() == FakeSHT4x.SERIAL_NUMBER
    t, rh = sensor.measure() or (0.0, 0.0)
    assert t == pytest.approx(31.25, abs=0.01)
    assert rh == pytest.approx(62.5, abs=0.01)


def test_sht4x_humidity_is_clipped_to_0_to_100() -> None:
    chip = FakeSHT4x()
    chip.set_measurement(temperature=20.0, humidity=110.0)
    sensor = QwiicSHT4x(0x44, i2c_driver=FakeQwiicBus({0x44: chip}))
    result = sensor.measure()
    assert result is not None
    assert result[0] == pytest.approx(20.0, abs=0.01)
    assert result[1] == 100.0


def test_sht4x_begin_fails_and_measure_returns_none_on_bad_crcs() -> None:
    chip = GarbledSHT4x()
    chip.on = True
    sensor = QwiicSHT4x(0x44, i2c_driver=FakeQwiicBus({0x44: chip}))
    assert not sensor.begin()
    assert sensor.measure() is None


def test_shtc3_measures_and_is_left_asleep() -> None:
    chip = FakeSHTC3()
    chip.set_measurement(temperature=31.25, humidity=62.5)
    sensor = QwiicSHTC3(i2c_driver=FakeQwiicBus({0x70: chip}))
    assert sensor.begin()
    assert chip.asleep
    t, rh = sensor.measure() or (0.0, 0.0)
    assert t == pytest.approx(31.25, abs=0.01)
    assert rh == pytest.approx(62.5, abs=0.01)
    assert chip.asleep


def test_shtc3_begin_finds_a_sensor_left_asleep() -> None:
    chip = FakeSHTC3()
    chip.asleep = True
    assert QwiicSHTC3(i2c_driver=FakeQwiicBus({0x70: chip})).begin()


def test_shtc3_is_put_back_to_sleep_after_a_reading_that_fails_its_crc() -> None:
    chip = GarbledSHTC3()
    sensor = QwiicSHTC3(i2c_driver=FakeQwiicBus({0x70: chip}))
    assert sensor.begin()
    chip.on = True
    assert sensor.measure() is None
    assert chip.asleep


def test_shtc3_begin_refuses_another_chip_id() -> None:
    class OtherId(FakeSHTC3):
        ID = 0x1234

    assert not QwiicSHTC3(i2c_driver=FakeQwiicBus({0x70: OtherId()})).begin()


def test_the_staging_package_imports_nothing_from_the_provider() -> None:
    # It is staged to go to SparkFun as it stands.
    root = Path(anolis_qwiic_staging.__file__).parent
    for source in root.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(n.startswith("anolis_provider") for n in names), source.name


# ---- the boards, through the provider --------------------------------------------


def provider(kind: str, chip: object) -> SparkFunProvider:
    p = SparkFunProvider({"mock": True, "devices": [{"id": "rh0", "type": kind}]})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr({"sht4x": SHT4x, "shtc3": SHTC3}[kind], "fake", staticmethod(lambda: chip))
        p.start(0.0)
    return p


@pytest.mark.parametrize(("kind", "chip_class"), [("sht4x", GarbledSHT4x), ("shtc3", GarbledSHTC3)])
def test_a_reading_that_fails_its_crc_is_unavailable_and_the_board_recovers(
    kind: str, chip_class: type[Garbled]
) -> None:
    chip = chip_class()
    p = provider(kind, chip)
    d = p.devices()[0]
    assert p.read(d, SIGNALS) == {
        "temperature": pytest.approx(22.5, abs=0.01),
        "relative_humidity": pytest.approx(40.0, abs=0.01),
    }
    chip.on = True
    with pytest.raises(ProviderError, match="CRC"):
        p.read(d, SIGNALS)
    health = p.device_health(d)
    assert health and health.state is DeviceState.UNREACHABLE
    chip.on = False
    assert set(p.read(d, SIGNALS)) == set(SIGNALS)


@pytest.mark.parametrize(("kind", "chip_class"), [("sht4x", GarbledSHT4x), ("shtc3", GarbledSHTC3)])
def test_a_chip_that_fails_its_id_check_is_unreachable(kind: str, chip_class: type[Garbled]) -> None:
    chip = chip_class()
    chip.on = True
    p = provider(kind, chip)
    health = p.device_health(p.devices()[0])
    assert health and health.state is DeviceState.UNREACHABLE
    assert "id check" in health.message


def test_an_absent_sht4x_is_reported_as_the_bus_error_not_a_failed_id_check() -> None:
    p = provider("sht4x", FakeSHT4x())
    bus = p._bus
    assert isinstance(bus, FakeQwiicBus)
    del bus.chips[0x44]
    p._slots["rh0"].driver = None  # connect again, to nothing
    with pytest.raises(ProviderError, match="not answering"):
        p.read(p.devices()[0], SIGNALS)
    health = p.device_health(p.devices()[0])
    assert health and health.state is DeviceState.UNREACHABLE
    assert "Errno 6" in health.message and "id check" not in health.message


def test_a_sleeping_shtc3_does_not_acknowledge_an_address_only_probe() -> None:
    # What makes the test above pin begin()'s choice not to probe first.
    chip = FakeSHTC3()
    sensor = QwiicSHTC3(i2c_driver=FakeQwiicBus({0x70: chip}))
    assert sensor.is_connected()
    chip.asleep = True
    assert not sensor.is_connected()


def test_sht4x_waits_as_long_for_its_serial_number_as_for_a_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr("anolis_qwiic_staging.qwiic_sht4x.time.sleep", waits.append)
    sensor = QwiicSHT4x(0x44, i2c_driver=FakeQwiicBus({0x44: FakeSHT4x()}))
    assert sensor.get_serial_number() == FakeSHT4x.SERIAL_NUMBER
    assert waits == [0.010]
