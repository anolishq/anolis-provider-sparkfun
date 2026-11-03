# AGENTS.md: anolis-provider-sparkfun

Per-repo conventions for coding agents.

## Build / test

- `just setup`, `just check` (ruff format, ruff lint, `mypy --strict`), `just test` (pytest), `just freeze` (PyInstaller).
- `just check && just test` is what CI runs, plus the frozen binary on x86_64 and arm64 under the harness. The required
  status check is the **`ok`** job.
- `tests/test_conformance.py` runs the anolis-protocol conformance harness against the provider in mock mode. A skip
  fails it unless listed in `EXPECTED_SKIPS` with a reason. `ANOLIS_PROVIDER_BIN` points it at another build.

## Design rules

- **The SDK on top of the vendor's driver.** A board module declares the device type and calls SparkFun's driver. A
  register the driver does not wrap may be read or written through the driver's own bus and register constants (as
  `scmd.py` does for the drive read-back and the watchdog); anything more, such as a protocol or a calculation the
  driver lacks, is fixed upstream or written as a driver in its own package, not inside a board module.
- **Mock mode runs the real driver.** The fake bus emulates the chip's registers; never stub the driver itself.
- **Only I2C transfer errors mean a board is unreachable** (`_BUS_ERRNOS` in `provider.py`). Any other exception is a
  provider fault and must surface as one.
- **Outputs: safe at connect, zero-rung drivable, read back from the chip.** See `docs/adding-a-board.md`, "Boards with
  outputs".
- **Only what the config names.** The provider opens one I2C bus and the configured addresses. It does not scan, and
  does not expose GPIO or SPI.

## Repo-specific gotchas

- `qwiic_i2c` picks its platform backend with `__import__` at import time. The PyInstaller spec collects every
  backend; mock mode never opens the real bus, so the harness does not cover that path. Check a frozen build with a
  non-mock config: it must fail with `cannot open /dev/i2c-<n>`, not an import error.
- The provider opens the bus with `qwiic_i2c`'s `LinuxI2C(iBus=n)`. SparkFun's unreleased main branch ignores `iBus`;
  `test_the_real_bus_opens_the_configured_bus_number` fails if an upgrade brings that in.
- SparkFun drivers write registers through `writeByte`, which smbus2 truncates to 8 bits without an error. Check a
  driver's arithmetic at the ends of its range (see `drive_args` in `devices/scmd.py`).
- `anolis-provider-sdk` is pinned by commit in `pyproject.toml` until it is published.
- Release binaries link the build runner's glibc (Ubuntu 24.04: 2.39).
- When running a mutation check, disable bytecode (`PYTHONDONTWRITEBYTECODE=1`).
