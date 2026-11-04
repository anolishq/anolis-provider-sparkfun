"""SparkFun Serial Controlled Motor Driver (SCMD) firmware on I2C: the Qwiic
Motor Driver (ROB-15451), and the Serial Controlled Motor Driver (ROB-13911)
strapped for I2C. Two DC motor channels, A and B (I2C 0x5D by default).

Driver: sparkfun-qwiic-scmd. Two registers it does not wrap are read and
written through the driver's own bus and register constants: the drive
registers, read back so the throttle signals show what the board holds, and
FSAFE_TIME, the board's watchdog.

Safe state: throttle 0 (drive register 0x80). The board drives both channels
there when it connects, at start-up and when it answers again after being lost,
again whenever it is found to have restarted on its own, and when the provider
exits (``stop``), however the session ends. Every motor
function has one required numeric argument, so the runtime's zero rung
(`safety.safe_state.zero_is_safe`) drives each one to 0.

The board has a command watchdog. With `failsafe_ms` set, a gap that long with
no completed I2C write sets both channels to 0x80 in the board's firmware,
whatever the provider or the host is doing. Every read and every call writes
to the board, which feeds it, so the runtime's polling keeps it fed. It covers
what ``stop`` cannot: if the runtime hangs, the provider is killed or hangs, or
the cable comes out, the motors stop within `failsafe_ms`.

Expansion-port slave boards (motors beyond A and B) are not supported.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

import qwiic_scmd
from anolis_provider_sdk import Arg, Category, DeviceType, Function, Signal, ValueType

from ..mock import FakeSCMD
from .base import DeviceDriver, NotAnswering

log = logging.getLogger(__name__)

MOTORS = {"a": 0, "b": 1}  # channel name: the driver's motor number
STOP = 0x80
SPAN = 127  # the firmware's own scale: 0x80 +/- 127 (customSerialInterrupts.c, the UART drive command)
FAILSAFE_DEFAULT_MS = 2000
ENUMERATION_TIMEOUT_S = 0.5


def _throttle_function(motor: str) -> Function:
    return Function(
        f"set_motor_{motor}_throttle",
        description=f"Drive motor channel {motor.upper()}. 0 stops it; the sign sets the direction.",
        args=(
            Arg(
                "throttle",
                ValueType.DOUBLE,
                min=-1.0,
                max=1.0,
                description="Fraction of the motor supply: -1 full reverse, 0 stop, 1 full forward",
            ),
        ),
        category=Category.ACTUATE,
        is_idempotent=True,
    )


TYPE = DeviceType(
    id="scmd",
    signals=(
        *(
            Signal(
                f"motor_{m}_throttle",
                ValueType.DOUBLE,
                description=f"Channel {m.upper()} throttle read back from the board: -1 to 1, 0 when stopped",
            )
            for m in MOTORS
        ),
        Signal(
            "failsafe_trips",
            ValueType.INT64,
            description="Times the board's watchdog has stopped the motors since it powered on (caps at 255)",
        ),
    ),
    functions=tuple(_throttle_function(m) for m in MOTORS),
)


def register_from_throttle(throttle: float) -> int:
    """The drive register value for a throttle: 0x80 +/- 127."""
    return STOP + round(max(-1.0, min(1.0, throttle)) * SPAN)


def throttle_from_register(value: int) -> float:
    """The throttle a drive register value means. 0x00, which only another
    master would write, reads as -1: the firmware drives it full reverse."""
    return max(-1.0, (value - STOP) / SPAN)


def drive_args(register: int) -> tuple[int, int]:
    """The (direction, level) for qwiic_scmd's set_drive that writes exactly
    ``register``. set_drive halves the level with Python's round(), so the level
    is chosen to land on the register rather than scaled from the throttle; a
    scaled level of 255 forward would compute 0x100, which goes out on the bus
    as 0x00, full reverse. Reported upstream:
    https://github.com/sparkfun/qwiic_scmd_py/issues/3"""
    step = register - STOP
    if step >= 0:
        return 1, 2 * step
    return 0, 2 * -step - 1


class SCMD(DeviceDriver):
    type = TYPE
    # Set by the config jumpers on the underside: the firmware answers I2C at
    # 0x58 + jumpers - 3 for jumper values 3 to 0xC (SCMD_FW serial.c and main.c).
    # sparkfun-qwiic-scmd lists only five of these:
    # https://github.com/sparkfun/qwiic_scmd_py/issues/4
    addresses = (0x5D, *(a for a in range(0x58, 0x62) if a != 0x5D))
    options = {
        "failsafe_ms": {
            "type": "integer",
            "minimum": 0,
            "maximum": 2550,
            "multipleOf": 10,
            "default": FAILSAFE_DEFAULT_MS,
            "description": (
                "Stop both motors in the board's firmware after this long with no I2C write from the provider. "
                "Keep it well above the runtime's polling.interval_ms. 0 turns the watchdog off."
            ),
        }
    }

    def __init__(self, i2c: Any, address: int, options: Mapping[str, Any]) -> None:
        self._bus = i2c
        self._address = address
        self._failsafe = options.get("failsafe_ms", FAILSAFE_DEFAULT_MS) // 10
        self._driver = qwiic_scmd.QwiicScmd(address, i2c_driver=i2c)
        found = self._driver.begin()
        if found != qwiic_scmd.QwiicScmd.ID_WORD:
            raise NotAnswering(f"no SCMD at {address:#04x}: ID register reads {found:#04x}")
        deadline = time.monotonic() + ENUMERATION_TIMEOUT_S
        while not self._driver.ready():
            if time.monotonic() > deadline:
                raise NotAnswering(f"SCMD at {address:#04x} has not finished starting up")
            time.sleep(0.01)
        self._make_safe()

    def _make_safe(self) -> None:
        """Both channels stopped, the watchdog armed, then the outputs enabled."""
        for motor in MOTORS.values():
            self._driver.set_drive(motor, *drive_args(STOP))
        self._write(qwiic_scmd.QwiicScmd.SCMD_FSAFE_TIME, self._failsafe)
        self._driver.enable()

    def _feed(self) -> None:
        """Restart the watchdog: a write of the register pointer alone, which
        the firmware counts as a completed write and changes nothing else by."""
        self._bus.writeCommand(self._address, qwiic_scmd.QwiicScmd.SCMD_STATUS_1)

    def _write(self, register: int, value: int) -> None:
        self._bus.writeByte(self._address, register, value)

    def _read(self, register: int) -> int:
        return int(self._bus.readByte(self._address, register))

    @staticmethod
    def fake() -> FakeSCMD:
        return FakeSCMD()

    def _check_restarted(self) -> None:
        """A board that restarted on its own (a brown-out on its supply) comes
        back disabled with the watchdog off; the provider leaves it enabled.
        Treat that as a new connection."""
        if not self._read(qwiic_scmd.QwiicScmd.SCMD_DRIVER_ENABLE) & 0x01:
            log.warning("SCMD at %#04x restarted; stopping its motors and re-arming its watchdog", self._address)
            self._make_safe()

    def read(self, signal_ids: list[str]) -> Mapping[str, Any]:
        self._feed()
        self._check_restarted()
        scmd = qwiic_scmd.QwiicScmd
        out: dict[str, Any] = {}
        for signal_id in signal_ids:
            if signal_id == "failsafe_trips":
                out[signal_id] = self._read(scmd.SCMD_FSAFE_FAULTS)
            else:
                motor = MOTORS[signal_id.removeprefix("motor_").removesuffix("_throttle")]
                out[signal_id] = round(throttle_from_register(self._read(scmd.SCMD_MA_DRIVE + motor)), 4)
        return out

    def call(self, function: Function, args: Mapping[str, Any]) -> Mapping[str, Any] | None:
        # The drive write itself feeds the watchdog.
        self._check_restarted()
        motor = MOTORS[function.name.removeprefix("set_motor_").removesuffix("_throttle")]
        self._driver.set_drive(motor, *drive_args(register_from_throttle(args["throttle"])))
        return None

    def stop(self) -> None:
        """Both channels to throttle 0, for when the provider exits. The outputs
        stay enabled and the watchdog keeps its configured period: the state
        connect leaves the board in. 0x80 already stops both channels, and
        nothing in the driver or its documentation says a disabled board is
        safer than an enabled one at 0x80."""
        error: Exception | None = None
        for motor in MOTORS.values():  # both, even if one fails
            try:
                self._driver.set_drive(motor, *drive_args(STOP))
            except Exception as err:
                error = error or err
        if error is not None:
            raise error
