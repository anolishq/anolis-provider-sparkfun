"""The ADS1015 board against the chip model: voltages per input, the input
range option, readings below ground, and the chips it refuses."""

from __future__ import annotations

import pytest
import qwiic_ads1015

from anolis_provider_sparkfun.devices.ads1015 import ADS1015, PROBE, signed12
from anolis_provider_sparkfun.devices.base import NotAnswering
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
    # change the conversion register still holds the old input's result, and the
    # driver reads it without waiting.
    # https://github.com/sparkfun/qwiic_ads1015_py/issues/1 (item 1)
    clock = Clock()
    chip = FakeADS1015(clock)
    chip.volts = [1.0, 2.0, 0.0, 0.0]
    driver = qwiic_ads1015.QwiicADS1015(ADDRESS, i2c_driver=FakeQwiicBus({ADDRESS: chip}))
    driver.get_single_ended(0)
    clock.now += 0.01
    assert driver.get_single_ended_millivolts(0) == pytest.approx(1000, abs=1)
    assert driver.get_single_ended_millivolts(1) == pytest.approx(1000, abs=1)  # input 1 is at 2 V


def test_below_ground_reads_negative_where_the_driver_reads_near_full_scale() -> None:
    # https://github.com/sparkfun/qwiic_ads1015_py/issues/1 (item 4)
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
    with pytest.raises(NotAnswering, match="config register reads"):
        ADS1015(FakeQwiicBus({ADDRESS: TMP102Like()}), ADDRESS, {})


def test_the_provider_reads_it_in_mock_mode() -> None:
    p = SparkFunProvider({"mock": True, "devices": [{"id": "adc0", "type": "ads1015", "full_scale_v": 2.048}]})
    p.start(0.0)
    assert p.device_health(p.devices()[0]) is None
    assert p.read(p.devices()[0], SIGNALS) == dict.fromkeys(SIGNALS, 0.0)


def test_addresses_are_the_drivers_with_the_factory_default_first() -> None:
    assert ADS1015.addresses == tuple(qwiic_ads1015.QwiicADS1015.available_addresses)


class TMP102:
    """A TI TMP102 temperature sensor, which also answers at 0x48: 16-bit
    registers behind a pointer. Its config register (pointer 1) powers on at
    0x60A0, converting; R1 and R0 (bits 14 and 13) read 1 and bits 3 to 0 read
    0, and SD (bit 8) shuts the sensor down. Records each register write."""

    def __init__(self) -> None:
        self.registers = {0: 0x1900, 1: 0x60A0, 2: 0x4B00, 3: 0x5000}
        self.writes: list[tuple[int, int]] = []
        self._pointer = 0

    def write(self, data: bytes) -> None:
        self._pointer = data[0] & 0b11
        if len(data) == 3 and self._pointer != 0:
            value = int.from_bytes(data[1:3], "big")
            self.writes.append((self._pointer, value))
            if self._pointer == 1:
                value = (value | 0x6000) & 0xFFF0
            self.registers[self._pointer] = value

    def select(self, register: int) -> None:
        self._pointer = register & 0b11

    def read(self, length: int) -> bytes:
        return self.registers[self._pointer].to_bytes(2, "big")[:length]


def test_a_tmp102_at_the_address_is_refused_and_left_as_it_was() -> None:
    chip = TMP102()
    with pytest.raises(NotAnswering, match="config register reads"):
        ADS1015(FakeQwiicBus({ADDRESS: chip}), ADDRESS, {})
    assert chip.writes[0] == (1, PROBE)  # the probe sets SD: the sensor shuts down
    assert chip.registers[1] == 0x60A0  # and it is converting again
    assert chip.writes[-1] == (1, 0x60A0)
