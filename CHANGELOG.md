# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-11

### Added

- The provider, built on the Python provider SDK and SparkFun's Qwiic Python
  drivers, with the SparkFun Qwiic Motor Driver (`scmd`) as its first board:
  two DC motor channels, stopped when the board connects, with the throttle
  read back from the board. The board's own watchdog (`failsafe_ms`, default
  2000) stops both motors if the provider stops writing to it.
- The TI ADS1015 (`ads1015`): four analog inputs in volts, with the input
  range as the `full_scale_v` option. Inputs below ground read negative, and a
  chip at the address that is not an ADS1015 is refused.
- The Bosch BME280 (`bme280`): temperature, humidity and pressure, with the
  same device type as the Adafruit provider's. A BMP280 at the address is
  refused, and a chip that restarted on its own is set up again.
- The Sensirion SHT40/41/45 (`sht4x`) and SHTC3 (`shtc3`): temperature and
  humidity, on drivers written for this provider in `anolis_qwiic_staging`,
  in SparkFun's driver style and staged to go to SparkFun, since SparkFun's
  Qwiic Python package has none for these chips.
- The Sensirion SCD40 and SCD41 (`scd4x`): CO2, temperature and humidity,
  measured every 5 seconds, with each reading stamped with when it was fetched.
  NaN with quality UNKNOWN until the first measurement; a sensor that stopped
  measuring is started again.
- The provider stops both SCMD channels when it exits, however the session
  ends (the runtime shuts down or closes the pipe, `SIGTERM`, a malformed
  frame), leaving the outputs enabled and the watchdog armed; a board that does
  not answer then is logged and skipped. Before, the motors ran on until the
  watchdog stopped them, or indefinitely with `failsafe_ms: 0`.
- Mock mode: a simulated bus with a register model of each board (the SCMD
  firmware, the ADS1015, the BME280, the SCD4x, the SHT4x and the SHTC3) that
  the board's driver runs against unchanged.
- A frozen single-file release binary for x86_64 and arm64, laid out for anolis
  `install.sh`, with the config schema assets the Workbench reads.
- `scripts/cold_start.py`, which measures start-up time on the target.

### Changed

- The Python provider SDK is pinned at 921808e. With it, the provider checks the
  host at start-up as `--check-host` does: when `/dev/i2c-<n>` is missing or the
  user cannot open it, the provider stays up but not ready and lists no devices,
  instead of listing every device as `UNREACHABLE`. Configs are read more
  strictly (a duplicated key, a NaN or infinity, or `2.0` where an integer is
  expected is refused); the shipped configs pass unchanged.

### Fixed

- A board is reported unreachable only for a failed I2C transfer or when the
  board module finds no board, another chip, or a board still starting
  (`NotAnswering`). Such a failure during a read or call now marks the board
  lost and reports it `UNREACHABLE` rather than `INTERNAL`, and any other
  exception from a board, a `RuntimeError` included, is a provider fault.
- When the I2C bus does not open, every device reports `UNREACHABLE` with the
  bus error, and the provider's own health is `FAULT`, instead of `OK`.
- An SHT4x that does not answer at all is reported with the bus error, not as
  a chip that failed its id check.
- Settings made through functions (the BME280's sea-level pressure, the
  SCD4x's ambient pressure) are applied again when a lost board is
  reconnected, in the order they were last set, instead of silently going
  back to their defaults.
- An SCD4x measurement now reads `STALE` after 12 s, before the board restarts
  a sensor that stopped measuring (after 20 s); before, the restart came at the
  same 15 s as the stale threshold, so a stuck sensor went from `OK` straight
  to NaN without ever reading `STALE`.
- The ADS1015 identity check writes back the config word it found when the
  chip at the address is not an ADS1015, so a TMP102 at 0x48 is no longer left
  shut down by the probe.
- The staged SHT4x driver waits 10 ms for the serial-number reply, as long as
  for a measurement and as Adafruit's SHT4x driver does, instead of 1 ms.
- `--check-config` and `--check-host` refuse a config that names a device id
  twice or puts two devices on one I2C address, with the same message as
  start-up; before, only `--config` refused it, when the provider was
  constructed, so a config that `--check-config` passed failed to start.
- `scripts/cold_start.py` reads each reply's status and the provider's
  readiness, and exits 1 with the reason, printing no figure, when Hello or
  WaitReady is not OK or the provider's start failed; before, a failed start
  still printed a ready time and exited 0.

[Unreleased]: https://github.com/anolishq/anolis-provider-sparkfun/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anolishq/anolis-provider-sparkfun/releases/tag/v0.1.0
