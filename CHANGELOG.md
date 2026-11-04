# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The provider, built on the Python provider SDK and SparkFun's Qwiic Python
  drivers, with the SparkFun Qwiic Motor Driver (`scmd`) as its first board:
  two DC motor channels, stopped when the board connects, with the throttle
  read back from the board. The board's own watchdog (`failsafe_ms`, default
  2000) stops both motors if the provider stops writing to it.
- Mock mode: a simulated bus with a register model of the SCMD firmware that
  SparkFun's driver runs against unchanged.

[Unreleased]: https://github.com/anolishq/anolis-provider-sparkfun/commits/main
