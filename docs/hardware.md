# Hardware

## Wiring a STEMMA QT or Qwiic board to a Raspberry Pi

STEMMA QT and Qwiic use the same 4-pin JST SH connector and pinout, and both
run at 3.3 V. Use a STEMMA QT/Qwiic cable to female jumpers, or a Qwiic adapter
board for the Pi header:

| Cable wire | Pi header pin |
| --- | --- |
| red, 3.3 V | 1 |
| blue, SDA | 3 (GPIO 2) |
| yellow, SCL | 5 (GPIO 3) |
| black, GND | 6 |

Boards daisy-chain on the same cable run: each needs its own address on the bus.

## The Qwiic Motor Driver

A Qwiic board with two DC motor channels, A and B, run by SparkFun's Serial
Controlled Motor Driver (SCMD) firmware. It daisy-chains on the Qwiic cable
like any other board.

- **Motor power is separate.** Motors run from the board's own motor supply
  input (SparkFun: 3 to 11 V, 12 V absolute maximum), not from the Qwiic cable.
  SparkFun rates each channel 1.2 A steady, 1.5 A peak; size the supply for the
  motors' stall current.
- **Channels:** A and B, one DC motor each. A motor that turns the wrong way for
  a positive throttle: swap its two wires.
- **Address:** `0x5D` from the factory. The config jumpers on the underside
  select `0x58` to `0x61`; the firmware reads them only at power-on.
- **Check it:** `i2cdetect -y 1` shows `5d`.

The provider stops both channels and arms the board's watchdog when it
connects. Before the first run, check that each motor can turn freely and that
nothing is attached that would move when it spins.

### Bench check of the software stop and the watchdog

With the runtime config's `safety.safe_state.zero_is_safe: true`, a motor on
channel A, and `failsafe_ms` at its default of 2000:

```sh
TOKEN=...   # from /etc/anolis/runtime.env when auth is on
H="Authorization: Bearer $TOKEN"
curl -s -H "$H" http://127.0.0.1:8080/v0/runtime/status | jq .startup_safe_state
curl -s -H "$H" -X POST http://127.0.0.1:8080/v0/call -H "Content-Type: application/json" \
  -d '{"provider_id":"sparkfun0","device_id":"drive0","function_id":1,"args":{"throttle":{"type":"double","double":0.3}}}'
curl -s -H "$H" -X POST http://127.0.0.1:8080/v0/estop | jq .safe_state_achieved
curl -s -H "$H" "http://127.0.0.1:8080/v0/state/sparkfun0/drive0?signal_id=motor_a_throttle" | jq '.values[0].value'
curl -s -H "$H" -X POST http://127.0.0.1:8080/v0/estop/clear
```

The motor should spin at the call, stop at the stop, and read back 0. Function
ids follow the channels: `set_motor_a_throttle` is 1, `set_motor_b_throttle` 2.

Then the watchdog: start the motor again with the same call, and stop the
runtime (`sudo systemctl stop anolis-runtime`, or kill it). The motor should
stop within about two seconds with nothing else done. After the runtime is back,
`failsafe_trips` reads 1 or more.

## The ADS1015

The Qwiic 12 Bit ADC carries a TI ADS1015: four analog inputs, A0 to A3.

- **Address:** `0x48` from the factory; the address jumper selects `0x49` to
  `0x4B`, four on one bus.
- **Input limits:** each input must stay between ground minus 0.3 V and the
  board's supply plus 0.3 V, which on Qwiic is 3.3 V. `full_scale_v` only sets
  the measuring range; a 5 V signal needs a divider whatever it says.
- **Check it:** `i2cdetect -y 1` shows `48`. Tie A0 to the 3.3 V pin and A1 to
  ground; `ain0` reads about 3.3 and `ain1` about 0.
- **Shared address:** a TMP102 temperature sensor also uses `0x48`; give one of
  them another address. The provider refuses a chip at the address that does
  not behave as an ADS1015.

## The BME280

The Qwiic Atmospheric Sensor carries a Bosch BME280: temperature, humidity and
pressure.

- **Address:** `0x77` from the factory; cut the address jumper for `0x76`, to
  run two on one bus.
- **Check it:** `i2cdetect -y 1` shows `77`, and the readings come back near
  the room's: about 20 to 25 C, 30 to 60 %, and roughly 950 to 1050 hPa at
  altitudes near sea level.
- **Placement:** keep it away from warm parts, the Pi's processor and motor
  drivers included; it reads its own surroundings.

## The SHT4x and SHTC3

Sensirion temperature and humidity sensors on SparkFun Qwiic boards: the
SHT40, SHT41 and SHT45 (`sht4x`) and the SHTC3 (`shtc3`).

- **Address:** `0x44` for the SHT4x, `0x70` for the SHTC3, both fixed: one of
  each per bus.
- **Check it:** `i2cdetect -y 1` shows `44`. An SHTC3 that the provider has
  already used is asleep between readings and may not show in `i2cdetect`;
  the provider wakes it for each reading.
- **Heater:** the SHT4x has a built-in heater, which the provider never turns
  on: run for long, it damages the sensor.

## The SCD4x

The Qwiic CO2 sensor carries a Sensirion SCD40 or SCD41: true CO2 by NDIR, with
temperature and humidity.

- **Address:** `0x62`, fixed: one per bus.
- **Check it:** `i2cdetect -y 1` shows `62`. Give it a minute after start-up,
  then expect roughly 400 to 1000 ppm indoors; breathing near it raises the
  reading within a few measurements.
- **Calibration:** automatic self-calibration is on, the sensor's default. It
  assumes the sensor sees fresh air (about 400 ppm) at some point every week;
  in a space that never does, readings drift.
- **Pressure:** the CO2 reading depends on air pressure. Pass a BME280's
  `pressure` to `set_ambient_pressure` for the best accuracy; it is not kept
  across a restart of the provider.
- **Placement:** the sensor warms itself slightly, so its temperature reads
  above the room's.

## Preparing the host

On Raspberry Pi OS:

```sh
sudo raspi-config nonint do_i2c 0   # enable I2C, then reboot
sudo usermod -aG i2c anolis         # the service user opens /dev/i2c-1
sudo apt install i2c-tools          # optional: i2cdetect for checking wiring
i2cdetect -y 1                      # a Qwiic Motor Driver shows as 5d
```

`install.sh` runs the provider's `--check-host` before installing and stops on
an unmet requirement. The provider reports whether `/dev/i2c-<n>` exists and
whether the user it runs as can open it.

## Measuring start-up time on the target

The runtime waits `hello_timeout_ms` (default 5000) for a provider's Hello
reply, then `ready_timeout_ms` for start-up to finish. The release binary is a
single self-extracting file, so its start-up is slower than a source install,
and slowest on first launch after boot. Measure it on the target with only
`python3` and the binary:

```sh
python3 scripts/cold_start.py /opt/anolis/bin/anolis-provider-sparkfun \
  /opt/anolis/projects/<project>/config/provider-sparkfun.yaml --runs 5
```

It prints the median and slowest time to the Hello reply and to the WaitReady
reply, and exits 1 if the slowest Hello is over `--hello-budget-ms`. Set the
runtime's `hello_timeout_ms` with room above the slowest figure.
