"""TI ADS1015 on SparkFun boards: the Qwiic 12 Bit ADC - 4 Channel (DEV-15334).
Four single-ended analog inputs, read as volts (I2C 0x48 by default; 0x49 to
0x4B with the address jumper).

Driver: sparkfun-qwiic-ads1015.

Each read is a single-shot conversion per input, waiting for the chip's
conversion-ready flag; the driver's default continuous mode returns the
previous input's result straight after switching inputs. Codes below ground
are sign-extended here, which the driver does not do, so a slightly negative
input reads as a small negative voltage rather than near full scale.

The driver waits for the conversion-ready flag with no timeout, so a chip that
answers at the address but never sets it would hang the provider. The chip has
no id register; the board checks that it holds a written config word as an
ADS1015 does (a TMP102, which also sits at 0x48, does not) and refuses
anything else.

An input above the chip's supply plus 0.3 V, or below ground minus 0.3 V,
can damage it, whatever ``full_scale_v`` says.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import qwiic_ads1015
from anolis_provider_sdk import DeviceType, Signal, ValueType

from ..mock import FakeADS1015
from .base import DeviceDriver, NotAnswering

ADS = qwiic_ads1015.QwiicADS1015
CHANNELS = 4
GAINS = {
    6.144: ADS.kConfigPgaTwoThirds,
    4.096: ADS.kConfigPga1,
    2.048: ADS.kConfigPga2,
    1.024: ADS.kConfigPga4,
    0.512: ADS.kConfigPga8,
    0.256: ADS.kConfigPga16,
}
FULL_SCALE_DEFAULT_V = 4.096  # covers 0 to 3.3 V, the Qwiic supply
# Single-shot, powered down, comparator off: what the identity check writes.
PROBE = ADS.kConfigModeSingle | ADS.kConfigCqueNone | ADS.kConfigRate1600Hz | ADS.kConfigPga1 | ADS.kConfigMuxSingle0

TYPE = DeviceType(
    id="ads1015",
    signals=tuple(
        Signal(
            f"ain{ch}",
            ValueType.DOUBLE,
            unit="V",
            description=f"Voltage on input A{ch} against ground, within +/- full_scale_v",
        )
        for ch in range(CHANNELS)
    ),
)


def signed12(code: int) -> int:
    """A 12-bit two's complement code as an int."""
    return code - (1 << 12) if code & 0x800 else code


class ADS1015(DeviceDriver):
    type = TYPE
    addresses = (0x48, 0x49, 0x4A, 0x4B)
    options = {
        "full_scale_v": {
            "enum": sorted(GAINS),
            "default": FULL_SCALE_DEFAULT_V,
            "description": (
                "Input range in volts, +/- this value: the chip's programmable gain. A smaller range resolves "
                "smaller voltages. It never raises what the inputs can take: no more than the supply plus 0.3 V."
            ),
        }
    }

    def __init__(self, i2c: Any, address: int, options: Mapping[str, Any]) -> None:
        self._bus = i2c
        self._address = address
        self._driver = ADS(address, i2c_driver=i2c)
        if not self._driver.begin():
            raise NotAnswering(f"no ADS1015 at {address:#04x}")
        self._check_identity()
        self._driver.set_gain(GAINS[float(options.get("full_scale_v", FULL_SCALE_DEFAULT_V))])
        # Single-shot, waiting on the chip's conversion-ready flag.
        self._driver.use_conversion_ready(True)

    def _check_identity(self) -> None:
        self._bus.writeBlock(self._address, ADS.kPointerConfig, [PROBE >> 8, PROBE & 0xFF])
        back = self._bus.readBlock(self._address, ADS.kPointerConfig, 2)
        found = (back[0] << 8) | back[1]
        if found != PROBE | ADS.kConfigOsReady:
            raise NotAnswering(f"no ADS1015 at {self._address:#04x}: its config register reads {found:#06x}")

    @staticmethod
    def fake() -> FakeADS1015:
        return FakeADS1015()

    def read(self, signal_ids: list[str]) -> Mapping[str, Any]:
        d = self._driver
        mv_per_count = d.get_multiplier()
        return {
            sid: signed12(d.get_single_ended(int(sid.removeprefix("ain")))) * mv_per_count / 1000 for sid in signal_ids
        }

    def call(self, function: Any, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        raise NotImplementedError("the ADS1015 declares no functions")
