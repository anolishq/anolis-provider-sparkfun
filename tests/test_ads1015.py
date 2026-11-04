"""The ADS1015 board against the chip model: voltages per input, the input
range option, readings below ground, and the chips it refuses."""

from __future__ import annotations

import pytest
import qwiic_ads1015

from anolis_provider_sparkfun.devices.ads1015 import ADS1015, signed12
from anolis_provider_sparkfun.mock import FakeADS1015, FakeQwiicBus, RegisterChip
from anolis_provider_sparkfun.provider import SparkFunProvider

ADDRESS = 0x48
SIGNALS = ["ain0", "ain1", "ain2", "ain3"]


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def connected(full_scale_v: float | None = None) -> tuple[ADS1015, FakeADS1015]:
    chip = FakeADS1015()
    options = {} if full_scale_v is None else {"full_scale_v": full_scale_v}
    return ADS1015(FakeQwiicBus({ADDRESS: chip}), ADDRESS, options), chip


def test_each_input_reads_its_own_voltage() -> None:
    s, chip = connected()
    chip.volts = [0.25, 1.5, 2.75, 3.3]
    r = s.read(SIGNALS)
    assert r == {sid: pytest.approx(v, abs=0.002) for sid, v in zip(SIGNALS, chip.volts, strict=True)}


def test_the_driver_default_mode_returns_the_previous_inputs_result() -> None:
    # Why the board reads single-shot: in continuous mode, straight after a mux
    # change the conversion register still holds the old input's result.
    clock = Clock()
    chip = FakeADS1015(clock)
    chip.volts = [1.0, 2.0, 0.0, 0.0]
    driver = qwiic_ads1015.QwiicADS1015(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: chip}))
    driver.get_single_ended(0)
    clock.now += 0.01
    assert driver.get_single_ended_millivolts(0) == pytest.approx(1000, abs=1)
    assert driver.get_single_ended_millivolts(1) == pytest.approx(1000, abs=1)  # input 1 is at 2 V


def test_below_ground_reads_negative_where_the_driver_reads_near_full_scale() -> None:
    s, chip = connected(2.048)
    chip.volts[0] = -0.002
    assert s.read(["ain0"])["ain0"] == pytest.approx(-0.002, abs=0.001)
    driver = qwiic_ads1015.QwiicADS1015(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: chip}))
    driver.use_conversion_ready(True)
    assert driver.get_single_ended_millivolts(0) > 4000


@pytest.mark.parametrize(
    ("full_scale_v", "volts", "expected"), [(6.144, 5.0, 5.0), (0.256, 0.1, 0.1), (0.256, 1.0, 0.2559)]
)
def test_the_range_option_sets_the_gain_and_clips_at_full_scale(
    full_scale_v: float, volts: float, expected: float
) -> None:
    s, chip = connected(full_scale_v)
    chip.volts[2] = volts
    assert s.read(["ain2"])["ain2"] == pytest.approx(expected, abs=full_scale_v / 2048)


def test_the_default_range_is_4_096_v() -> None:
    s, chip = connected()
    chip.volts[0] = 3.3
    assert s.read(["ain0"])["ain0"] == pytest.approx(3.3, abs=0.002)
    assert ADS1015.options["full_scale_v"]["default"] == 4.096


def test_signed12() -> None:
    assert [signed12(c) for c in (0x000, 0x7FF, 0x800, 0xFFF)] == [0, 2047, -2048, -1]


class TMP102Like(RegisterChip):
    """Another chip at 0x48 with 16-bit registers that does not hold the
    written config as an ADS1015 does."""

    def write(self, data: bytes) -> None:
        if len(data) == 3:
            self.registers[data[0]] = data[1] & 0x60  # most bits read-only
            self.registers[data[0] + 1] = data[2] & 0xF0
            self._pointer = data[0]
        else:
            super().write(data)


def test_a_chip_that_does_not_hold_the_config_is_refused() -> None:
    with pytest.raises(ValueError, match="config register reads"):
        ADS1015(FakeQwiicBus({ADDRESS: TMP102Like()}), ADDRESS, {})


def test_the_provider_reads_it_in_mock_mode() -> None:
    p = SparkFunProvider({"mock": True, "devices": [{"id": "adc0", "type": "ads1015", "full_scale_v": 2.048}]})
    p.start(0.0)
    assert p.device_health(p.devices()[0]) is None
    assert p.read(p.devices()[0], SIGNALS) == dict.fromkeys(SIGNALS, 0.0)


def test_addresses_are_the_drivers_with_the_factory_default_first() -> None:
    assert ADS1015.addresses == tuple(qwiic_ads1015.QwiicADS1015.available_addresses)
