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
- Mock mode: a simulated bus with a register model of each board (the SCMD firmware, the ADS1015, the BME280, the SCD4x) that
  SparkFun's driver runs against unchanged.

[Unreleased]: https://github.com/anolishq/anolis-provider-sparkfun/commits/main
