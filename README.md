# anolis-provider-sparkfun

An [Anolis](https://github.com/anolishq/anolis) device provider for SparkFun
Qwiic hardware. It puts the
[Python provider SDK](https://github.com/anolishq/anolis-provider-sdk-python) on
top of SparkFun's own [Qwiic Python drivers](https://github.com/sparkfun/Qwiic_Py),
so each board is a short declaration plus a call into the driver SparkFun
already maintains.

> **Status: unreleased.** It passes the anolis-protocol 1.10.0 conformance
> harness at level 2 in mock mode, from source and as the frozen binary, on
> x86_64 and arm64. Not yet verified on hardware.

## Supported boards

| `type` | Board | Driver | Addresses |
| --- | --- | --- | --- |
| `ads1015` | Qwiic 12 Bit ADC - 4 Channel (DEV-15334): four analog inputs, in volts | `sparkfun-qwiic-ads1015` | `0x48` (default), `0x49` to `0x4B` |
| `bme280` | Qwiic Atmospheric Sensor (SEN-15440), and the BME280 on SparkFun's Environmental Combo: temperature, humidity, pressure | `sparkfun-qwiic-bme280` | `0x77` (default), `0x76` |
| `scd4x` | Qwiic CO2 Humidity and Temperature Sensor, SCD40 or SCD41 (SCD41: SEN-22396): CO2, temperature, humidity | `sparkfun-qwiic-scd4x` | `0x62` |
| `scmd` | Qwiic Motor Driver (ROB-15451), and the Serial Controlled Motor Driver (ROB-13911) strapped for I2C: two DC motors | `sparkfun-qwiic-scmd` | `0x5D` (default), `0x58` to `0x61` |

All boards share one Linux I2C bus (`i2c_bus`, default 1: the Raspberry Pi
header, and any Qwiic or STEMMA QT adapter on it).

## Config

```yaml
i2c_bus: 1
devices:
  - id: drive0
    type: scmd
    label: Pump drive
    failsafe_ms: 2000
  - id: env0
    type: bme280
    label: Enclosure air
  - id: air0
    type: scd4x
    label: Enclosure CO2
  - id: adc0
    type: ads1015
    full_scale_v: 4.096
```

`mock: true` replaces the bus with a simulated one holding a register model of
each configured board. SparkFun's driver runs unchanged against it. The full
schema: `anolis-provider-sparkfun --config-schema`.

A board that does not answer is listed anyway and reported `UNREACHABLE`; reads
and calls fail with `UNAVAILABLE` and retry the board each time, so reseating a
cable recovers it without a restart.

## The ADS1015

`ads1015` reads `ain0` to `ain3` in volts, each against ground, with
`full_scale_v` (6.144, 4.096, 2.048, 1.024, 0.512 or 0.256; default 4.096)
setting the range: a reading beyond it clips at it. The range does not change
what the inputs can take, which is ground minus 0.3 V to the supply plus 0.3 V.
Each read converts each requested input in turn, about 2 ms an input; a
slightly negative input reads negative.

## The BME280

`bme280` declares the same signals and functions as the Adafruit provider's
`bme280`: `temperature` (C), `relative_humidity` (%) and `pressure` (hPa), with
`altitude` and `sea_level_pressure` on request, `set_sea_level_pressure` and
`soft_reset`. The provider refuses a BMP280 at the address, which has no
humidity sensor, and sets the chip up again if it finds it has restarted on its
own: a restarted BME280 does not fail, it reads plausible wrong values.

## The SCD4x

`scd4x` reads `co2` (ppm), `temperature` (C) and `relative_humidity` (%). The
sensor measures every 5 seconds on its own, so a read returns the latest
measurement, stamped with the time it was fetched. Until the first one, about
5 seconds after start-up, each signal reads NaN with quality `UNKNOWN`; a
measurement older than 15 seconds reads `STALE`. `set_ambient_pressure` (hPa)
compensates the CO2 reading, for example from a BME280 on the same bus. A
sensor that restarted on its own stops measuring without an error; the provider
notices when no measurement has arrived for 15 seconds and starts it again.

Connecting stops any measurement already running, which the sensor answers
only after 500 ms, so a configured SCD4x adds half a second to the provider's
start-up.

## Motors, the software stop and the watchdog

`scmd` has one function per channel, `set_motor_a_throttle(throttle)` and
`set_motor_b_throttle(throttle)`, with `throttle` from -1 to 1, where 0 stops
the motor. Each `motor_<a|b>_throttle` signal is read back from the board.

The board stops both channels when it connects: at start-up, when it answers
again after being lost, and when the provider finds it has restarted on its own
(a brown-out on its supply). So a supervised restart of the provider stops the
motors, whatever `safety.on_startup` says.

Throttle 0 is the safe state, so the runtime's zero rung drives it:

```yaml
safety:
  safe_state:
    zero_is_safe: true
```

With that, the startup safe state and `POST /v0/estop` stop every motor.

Unlike most motor boards, this one has a **command watchdog** in its firmware.
With `failsafe_ms` set (default 2000, 10 to 2550 in steps of 10, 0 for off), the
board stops both motors itself after that long with no I2C write. Every read
writes to the board, so the runtime's polling (`polling.interval_ms`, 500 by
default) keeps it fed. If the runtime hangs or stops, the provider dies or the
cable comes out, the motors stop within `failsafe_ms`. Keep it well above the
polling interval: each trip is counted in the `failsafe_trips` signal.

It is still a software stop, not an emergency stop: cut the motor supply for
that. See the runtime's
[safety guide](https://github.com/anolishq/anolis/blob/main/docs/safety.md).

## Install

Pin it in a machine profile like any provider. `install.sh` installs from any
`owner/repo`:

```yaml
components:
  providers:
    sparkfun:
      repo: anolishq/anolis-provider-sparkfun
      version: "<version>"
```

and give the runtime config an entry for it:

```yaml
providers:
  - id: sparkfun0
    command: /opt/anolis/bin/anolis-provider-sparkfun
    args: ["--config", "/opt/anolis/projects/<project>/config/provider-sparkfun.yaml"]
    hello_timeout_ms: 5000
    ready_timeout_ms: 10000
```

The host needs I2C enabled and the `anolis` user in the `i2c` group;
`--check-host` reports both. See [docs/hardware.md](docs/hardware.md) for
wiring, host preparation and measuring start-up time on the target.

Release binaries are built on Ubuntu 24.04 and need glibc 2.39 or newer: Debian
13 (Raspberry Pi OS trixie) or Ubuntu 24.04 and later.

## Development

Requires [uv](https://docs.astral.sh/uv/) and [just](https://just.systems/).

```sh
just setup    # uv sync --locked --extra dev
just check    # ruff format check, ruff lint, mypy --strict
just test     # unit tests, and the conformance harness in mock mode
just freeze   # the single-file release binary, in dist/
```

Adding a board: [docs/adding-a-board.md](docs/adding-a-board.md).

## License

Apache-2.0. See [LICENSE](LICENSE). SparkFun's drivers are MIT-licensed.
