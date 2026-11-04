# Adding a board

A board is one module in `src/anolis_provider_sparkfun/devices/`, registered in
`devices/__init__.py` under the `type` a config names it with. It holds:

- **The declaration**: a `DeviceType` listing the board's signals and functions
  (see the SDK's guide to writing a provider). The SDK derives function ids,
  default reads and argument validation from it.
- **A `DeviceDriver` subclass** that constructs SparkFun's driver for the board, passing
  the provider's bus as `i2c_driver`,
  and maps signals and function calls onto it. Keep it thin: the driver does the
  work.
- **`addresses`**: the I2C addresses the board can be strapped to, factory
  default first. The config schema accepts only these. Take them from the
  board's firmware or datasheet: a driver's `available_addresses` can be short.
- **`options`**: any per-device config keys the board takes beyond `id`,
  `type`, `address` and `label`, as JSON Schema with a default.
- **`fake()`**: a register model of the chip for mock mode, in `mock.py`.

## When the board does not answer

The provider reports a board UNREACHABLE, and tries it again on the next read
or call, for exactly two exceptions: an `OSError` from a failed I2C transfer
(an errno in `_BUS_ERRNOS` in `provider.py`), and `NotAnswering` from
`devices/base.py`. Raise `NotAnswering`, with a message saying what was found,
when the board at the address is absent, is a different chip, or has not
finished starting, whether at connect or when the board sets the chip up again
during a read or call. Where the driver signals one of those by raising, catch
that exception narrowly and raise `NotAnswering` from it. Every other
exception, a `ValueError` or `RuntimeError` included, is a fault in the
provider and is reported as one.

## Settings

A function whose category is `CONFIG`, that is idempotent and that takes at
least one argument is a setting, such as the BME280's
`set_sea_level_pressure`. The provider records the latest arguments of each
setting called on a board and, when it reconnects that board after losing it,
calls them again on the new driver, in the order they were last set: a new
driver starts from its defaults, and the chip may have lost power with the
cable. Declare a function that way only if calling it again with the same
arguments puts the setting back. A setting that fails to apply again leaves the
board lost, like any failed transfer, and the next read or call retries it.

## The fake chip

Mock mode runs SparkFun's real driver against `FakeQwiicBus`, so the fake has to
behave like the chip at the register level: the id register, calibration data,
and raw readings the driver converts. Take the values from the datasheet's
worked example where it has one, and test that the driver's output matches the
datasheet (see `tests/test_mock.py`). Many Qwiic boards run SparkFun firmware on
a microcontroller rather than a fixed-function chip; for those, model what the
published firmware source does, and cite the file. A fake the driver accepts is
evidence the model is right; one written to match the provider's own code is
not.

## Boards with outputs

A board that drives anything (a motor, a relay, a heater) has three more rules,
from the runtime's safety contract:

- **Drive the safe state when the board connects.** The constructor runs at
  start-up and again when a lost board answers, and leaves every output safe.
  Name the safe state in the module docstring.
- **Drive it again when the provider exits.** Override `stop()`: the provider
  calls it on every connected board when the session ends, however it ends,
  logs and skips a board that does not answer, and goes on to the next.
- **Give every `ACTUATE` function a required numeric argument for which 0 is
  safe and in range.** The runtime's zero rung (`safety.safe_state.zero_is_safe`)
  calls each actuating function with its required numeric arguments set to 0,
  and counts any function it cannot do that for as a failure, so the software
  stop then reports `safe_state_achieved: false`. That rules out a function with
  no arguments, a required boolean or string, and a channel-index argument (0 is
  not a channel). Use one function per output instead, as `scmd` does.
- **Read outputs back from the chip,** not from what the driver was last told,
  so a signal shows what the hardware is doing. A register pattern the
  firmware or chip gives a meaning reads as that meaning with quality `OK`,
  even one the provider never writes: `scmd` reads drive register 0x00 as -1,
  because the firmware drives 0x00 full reverse, and another master on the bus
  may have written it. Quality `UNKNOWN` is for a pattern that means nothing
  the hardware does.

Say in the module whether the board has a command watchdog, and use it when it
has one, as `scmd` does. `stop()` runs only when the provider exits in order;
without a watchdog, the outputs hold their last value if the provider is killed
or hangs.

## Before opening a PR

- Add the board to `config/conformance.yaml`, so the harness covers it.
- `just check && just test`.
- `just freeze`, then run the harness against the frozen binary:
  `ANOLIS_PROVIDER_BIN=$PWD/dist/anolis-provider-sparkfun uv run pytest tests/test_conformance.py`.
  A driver may load data files or modules that only the frozen build misses.
- Read the board on real hardware, and say in the PR which board and which
  readings you checked.
