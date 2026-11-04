# Coverage: candidate SparkFun boards

Which SparkFun Qwiic boards this provider could support, grouped by the chip
and the SparkFun Qwiic Python driver that runs it, not by SKU. A row is one
unit of work: a module in `devices/` as described in
[adding-a-board.md](adding-a-board.md). Every driver here takes an injected
bus (`i2c_driver=`), which is how the provider shares one Linux bus and
substitutes a fake one in mock mode.

Supported today: the Qwiic Motor Driver (SCMD), the ADS1015, the BME280, the
SCD4x, and the SHT4x and SHTC3 on this repo's own drivers. Everything else is
a candidate.

Sources, all retrieved 2026-11-03:

- `sparkfun/Qwiic_Py`, `.gitmodules` on `main`: SparkFun's own list of Python
  drivers, in two groups, `drivers/` and `drivers_linux_only/`.
- Each listed driver repository (`main`, else `master`): `README.md`
  ("Supported SparkFun Products" section), `pyproject.toml` or `setup.py`,
  `LICENSE`, and the driver module.
- The sparkfun.com product page each README links to: SKU and current product
  name. Several old links redirect; the SKU given is the page the link lands
  on, and a redirect to a different product is flagged.
- For the SCMD only: SparkFun's *Serial Controlled Motor Driver (SCMD)
  Datasheet and Manual*, and the SCMD firmware source in
  `sparkfun/Serial_Controlled_Motor_Driver` (`Firmware/SCMD_FW.cydsn`).

The address column is the driver's `_AVAILABLE_I2C_ADDRESS` list (or
equivalent constant), default first. Where no fetched source stated a fact,
the cell says **unconfirmed**.

Every driver is MIT-licensed except the u-blox GPS driver (GPL-3.0) and the
Titan GPS driver (no `LICENSE` file found). GPL code in the frozen release
binary would change the binary's licence terms; keep it out.

## Actuators and outputs

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| SCMD (Serial Controlled Motor Driver firmware, 2 H-bridge channels) | `sparkfun_qwiic_scmd` | Qwiic Motor Driver (ROB-15451); Auto pHAT (ROB-16328), which also carries a PCA9685, an encoder reader and an ICM-20948 | 0x5D (default), 0x58 to 0x61 (firmware `serial.c`: 0x58 + jumpers - 3; the driver lists five) | **Supported** (`scmd`). `set_drive(motor, direction, level)` with level 0 writes 0x80, which the datasheet says "will appear as off at the outputs", so 0 is safe and in range. Power-on state: drivers disabled, outputs zero (datasheet). **Has a hardware watchdog**: `FSAFE_TIME` (0x76), 10 ms per LSB up to 2.55 s, 0 = off (the default); on expiry the firmware sets both drive registers to 0x80, stop (`main.c`, `FSAFE_TIMER_Interrupt`; `FSAFE_CTRL` default includes `DRIVE_KILL`). The Python driver defines the register but has no setter, so the provider writes it through the driver's bus. `set_drive(m, 1, 255)` sends 0x00, full reverse; the provider avoids that level. One function per channel fits the zero rung. Slave boards chain behind the master on its expansion bus; the driver addresses motors 0-33 through the master's I2C address. |
| PCA9685 16-channel PWM | `sparkfun_qwiic_pca9685`; `sparkfun_pi_servo_hat` wraps it | Servo pHAT (DEV-15316); Auto pHAT (ROB-16328) servo outputs | 0x40 to 0x7F (driver accepts the full range) | Same chip as Adafruit's servo boards: a 0 angle is a position; 0 pulse width is off. No watchdog. Both READMEs link the Servo pHAT; no standalone SparkFun PCA9685 breakout was found in the sources. |
| Qwiic Relay firmware (ATtiny) | `sparkfun_qwiic_relay` | Single Relay (COM-15093); Quad Relay (COM-16566); Dual Solid State Relay (COM-16810); Quad Solid State Relay Kit (KIT-16833) | single 0x18/0x19; quad 0x6D/0x6C; dual SSR 0x0A/0x0B; quad SSR 0x08/0x09 (default/jumper closed) | Off is the safe state (`set_relay_off`). `set_slow_pwm(relay, value)` on the SSR boards gives a numeric argument where 0 is off, which fits the zero rung; on/off relays need one function per relay with a numeric argument. Power-on relay state and any watchdog: **unconfirmed** (not in the driver or product pages). Address is software-changeable (`change_address`). |
| MCP4725 12-bit DAC | `sparkfun_qwiic_mcp4725` | I2C DAC Breakout - MCP4725 (BOB-12918) | 0x60, 0x61 | 0 V output. Whether the board restores a stored EEPROM value at power-up is **unconfirmed** here; drive 0 on connect regardless. |
| APA102C LED stick | `sparkfun_qwiic_led_stick` | Qwiic LED Stick (COM-18354) | 0x23, any 0x08-0x77 by software | Indicator, not an actuator. |

## Discrete I/O (GPIO expanders)

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| TCA9534 8-bit expander | `sparkfun_qwiic_gpio` | Qwiic GPIO (DEV-17047) | 0x27 default, 0x20-0x27 by jumper | The product page names the TCA9534 and the 0x27 default. Screw terminals; suits interlock inputs and simple outputs. Interrupt pin out of scope; poll. |

## Analog in (ADCs, load cell)

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| NAU7802 24-bit bridge ADC | `sparkfun_qwiic_nau7802` | Qwiic Scale - NAU7802 (SEN-15242) | 0x2A | Load cells. Same chip as Adafruit 4538. |
| ADS1015 12-bit 4-channel | `sparkfun_qwiic_ads1015` | Qwiic 12 Bit ADC - 4 Channel (DEV-15334) | 0x48 (default) to 0x4B | **Supported** (`ads1015`): four inputs in volts, range as `full_scale_v`. The driver's default continuous mode returns the previous input's result after a mux change, its conversion-ready wait has no timeout, and it does not sign-extend single-ended codes; the provider reads single-shot, checks the chip by config read-back and sign-extends. |

## Environment

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| BME280 | `sparkfun_qwiic_bme280` | Atmospheric Sensor Breakout - BME280 (SEN-15440); Environmental Combo ENS160/BME280 (SEN-22858) | 0x77, 0x76 | **Supported** (`bme280`), same device type as the Adafruit provider's. The driver accepts a BMP280 (no humidity); the provider refuses it, and sets up again a chip that restarted asleep. The combo board carries two chips: one module per chip, two config entries. |
| BMP581 | `sparkfun_qwiic_bmp581` | Pressure Sensor - BMP581 (SEN-20170); Micro Pressure Sensor - BMP581 (SEN-20171) | 0x47, 0x46 | |
| MicroPressure | `sparkfun_qwiic_micropressure` | Qwiic MicroPressure Sensor (SEN-16476) | 0x18 | Ported gauge. Sensor part number not in the fetched sources (**unconfirmed**). |
| TMP117 | `sparkfun_qwiic_tmp117` | High Precision Temperature Sensor - TMP117 (SEN-15805) | 0x48 to 0x4B | |
| TMP102 | `sparkfun_qwiic_tmp102` | Digital Temperature Sensor - TMP102 (SEN-16304) | 0x48 to 0x4B | |
| AS6212 | `sparkfun_qwiic_as6212` (Linux only) | Digital Temperature Sensor Breakout - AS6212 (SEN-18521) | 0x48 default, 0x44-0x4B | |
| MCP9600 thermocouple | `sparkfun_qwiic_mcp9600` | Qwiic Thermocouple Amplifier - MCP9600 (SEN-16295) | 0x60 | Note the different default from Adafruit's MCP9601 board (0x67). |
| FS3000 air velocity | `sparkfun_qwiic_fs3000` | Air Velocity Sensor FS3000-1005 (SEN-18377); FS3000-1015 (SEN-18768) | 0x28, fixed | Airflow, e.g. hood or duct checks. |
| Soil moisture | `sparkfun_qwiic_soil_moisture_sensor`; `sparkfun_qwiic_cy8cmbr3` | Qwiic Soil Moisture Sensor (SEN-17731); Qwiic Soil Moisture Sensor (Capacitive) (SEN-30480) | 0x28; 0x37 | Two different drivers. |

## Gas and air quality

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| SCD4x NDIR CO2 | `sparkfun_qwiic_scd4x` | CO2 Humidity and Temperature Sensor - SCD41 (SEN-22396) | 0x62 | **Supported** (`scd4x`): measures every 5 s; NaN with QUALITY_UNKNOWN before the first measurement, STALE after 12 s, and restarted after 20 s with no measurement. The driver's `begin()` returns True whatever it found; the provider checks the serial read and restarts a sensor that stopped measuring. |
| SGP40 VOC | `sparkfun_qwiic_sgp40` | Air Quality Sensor - SGP40 (SEN-18345) | 0x59 | Ships its own VOC index algorithm module. |
| ENS160 MOX | `sparkfun_qwiic_ens160` | Indoor Air Quality Sensor - ENS160 (SEN-20844); Environmental Combo (SEN-22858) | 0x53, 0x52 | |
| CCS811 | `sparkfun_qwiic_ccs811` (Linux only) | **unconfirmed**: the README's product link (14348) now redirects to the ENS160/BME280 combo | 0x5B, 0x5A | Probably retired; low priority. |

## Motion and IMU

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| ISM330DHCX | `sparkfun_qwiic_ism330dhcx` | 6DoF IMU Breakout - ISM330DHCX (SEN-19764) | 0x6B, 0x6A | |
| LSM6DSO | `sparkfun_qwiic_lsm6dso` | 6 Degrees of Freedom Breakout - LSM6DSO (SEN-18020) | 0x6B, 0x6A | |
| ICM-20948 | `sparkfun_qwiic_icm20948` | Auto pHAT (ROB-16328); standalone board **unconfirmed**: the README links 15318, which now redirects to SEN-19895 (ISM330DHCX + MMC5983MA) | 0x69, 0x68 | |
| KX13x | `sparkfun_qwiic_kx13x` | Triple Axis Accelerometer Breakout - KX134 (SEN-17589) | 0x1F, 0x1E | |
| ADXL313 | `sparkfun_qwiic_adxl313` (Linux only) | Triple Axis Digital Accelerometer Breakout - ADXL313 (SEN-17241) | 0x1D, 0x53 | |
| MMC5983MA magnetometer | `sparkfun_qwiic_mmc5983ma` | Micro Magnetometer - MMC5983MA (SEN-19921) | 0x30 | |
| PAA5160E1 optical odometry | `sparkfun_qwiic_otos` | Optical Tracking Odometry Sensor (SEN-24904) | 0x17 | Mobile robots; low lab value. |

## Distance and ToF

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| VL53L1X | `sparkfun_qwiic_vl53l1x` | Distance Sensor Breakout - 4 Meter, VL53L1X (SEN-14722) | 0x29 | All default to 0x29; a mux is the simplest way to run several. |
| VL53L5CX 8x8 imager | `sparkfun_qwiic_vl53l5cx` | Qwiic ToF Imager - VL53L5CX (SEN-18642) | 0x29 | The package ships a `vl53l5cx_bin` firmware blob, so connect is probably slow (**unconfirmed**). |
| HC-SR04 ultrasonic with I2C firmware | `sparkfun_qwiic_ultrasonic` | Qwiic Ultrasonic Distance Sensor - HC-SR04 (SEN-17777) | 0x2F default, 0x20 and up | |
| VCNL4040 proximity | `sparkfun_qwiic_proximity` (Linux only) | Proximity Sensor Breakout - 20cm, VCNL4040 (SEN-15177) | 0x60 | |
| PIR | `sparkfun_qwiic_pir` (Linux only) | Qwiic PIR 170 uA (SEN-17374); 1 uA (SEN-17375) | 0x12, any by software | Presence; door or enclosure occupancy. |

## Light and colour

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| VEML6030 lux | `sparkfun_qwiic_veml6030` | Ambient Light Sensor - VEML6030 (SEN-15436) | 0x48, 0x10 | |
| AS726x / AS7265x / AS7343 spectral | `sparkfun_qwiic_as726x`, `_as7265x`, `_as7343` | Spectral Sensor - AS7262 Visible (SEN-14347); Triad Spectroscopy - AS7265x (SEN-15050); Spectral Sensor - AS7343 (SEN-23220) | 0x49; 0x49; 0x39 | AS7265x is 18 channels across three dies. Plate and liquid colour. |
| MAX3010x photodetector | `sparkfun_qwiic_max3010x` | Photodetector Breakout - MAX30101 (SEN-16474) | 0x57 | Pulse-oximetry part; low lab value. |

## Power monitoring

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| MAX1704x fuel gauge | `sparkfun_qwiic_max1704x` | LiPo Fuel Gauge (TOL-20680) | 0x36 | Battery rigs only. SparkFun's Python list has no current/power monitor (no INA-family driver). |

## Human input

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| Qwiic Button firmware | `sparkfun_qwiic_button` | Qwiic Button Red LED (BOB-15932); Green LED (BOB-16842); Button Breakout (BOB-15931) | 0x6F, any 0x08-0x77 by software | A physical "run/stop" input for a rig. Has an LED output too. |
| Qwiic Twist encoder | `sparkfun-qwiic-twist` | Qwiic Twist - RGB Rotary Encoder (DEV-15083) | 0x3F, changeable | |
| Qwiic Keypad | `sparkfun_qwiic_keypad` | Qwiic Keypad - 12 Button (COM-15290) | 0x4B, changeable | |
| Qwiic Joystick | `sparkfun-qwiic-joystick` | Qwiic Joystick (COM-15168) | 0x20, changeable | |
| CAP1203 touch slider | `sparkfun_qwiic_cap1203` | Capacitive Touch Slider - CAP1203 (SEN-15344) | 0x28 | |
| Dual Encoder Reader firmware | `sparkfun_qwiic_dual_encoder_reader` (Linux only) | Auto pHAT (ROB-16328) | 0x73, 0x74 | Motor encoder counts; pairs with the SCMD on the Auto pHAT. |
| Top pHAT buttons | `sparkfun_top_phat_button` (Linux only) | Top pHAT for Raspberry Pi (DEV-16301) | 0x71 | |

## Displays

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| SerLCD character LCD | `sparkfun_qwiic_serlcd` | 16x2 RGB Backlight (LCD-16396); 16x2 RGB Text (LCD-16397); 20x4 RGB Backlight (LCD-16398) | 0x72, changeable | Rig status line. |
| Qwiic OLED | `sparkfun_qwiic_oled_base` | Qwiic OLED 0.91" 128x32 (LCD-24606); 1.3" 128x64 (LCD-23453); Micro OLED (LCD-22495) | 0x3D, 0x3C | |
| Alphanumeric display | `sparkfun_qwiic_alphanumeric` | Qwiic Alphanumeric Display - Red (COM-16916) | 0x70 to 0x73 | Controller chip not in the fetched sources (**unconfirmed**). |

## Bus infrastructure

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| TCA9548A 8-channel mux | `sparkfun_qwiic_tca9548a` | Qwiic Mux Breakout - 8 Channel (BOB-16784; the README's link 14685 redirects there) | 0x70 to 0x77 | **Bus device.** The provider owns channel selection and routes each board behind it. Same design question as in the Adafruit provider; settle it once for both. |

## Other

| Chip / family | PyPI driver | Example boards (SKU) | I2C address | Notes for Anolis |
| --- | --- | --- | --- | --- |
| RV-8803 RTC | `sparkfun_qwiic_rv8803` | Real Time Clock Module - RV-8803 (BOB-16281) | 0x32 | Low value. |
| EEPROM | `sparkfun_qwiic_eeprom` (Linux only) | Qwiic EEPROM Breakout - 512Kbit (COM-18355) | 0x50 to 0x57 | Not a runtime device. |
| RFID reader firmware | `sparkfun_qwiic_rfid` | RFID Qwiic Reader (SEN-15191) | 0x13, 0x14, others by software | Sample or operator tagging. |
| HuskyLens | `sparkfun_qwiic_huskylens` | **unconfirmed**: README names no product | 0x32 | Vision module; low value. |
| XA1110 GPS | `sparkfun_qwiic_titan_gps` | GPS Breakout - XA1110 (GPS-14414) | **unconfirmed** | No `LICENSE` file found. Low value. |
| u-blox GPS | `sparkfun_ublox_gps` | GPS-15005, 15136, 15193, 15210, 15733, 16475, 22693 (README) | **unconfirmed** | **GPL-3.0**: keep out of the frozen binary. Listed twice in `.gitmodules` (both groups, same repository). |

## Overlap with the Adafruit provider

This provider runs SparkFun boards on SparkFun's drivers, and
`anolis-provider-adafruit` runs Adafruit boards on Adafruit's. Each covers its
own vendor's boards completely, even where the other already supports the same
chip: someone with only SparkFun boards should not need the Adafruit provider.
Where both support a chip, they declare the same device type (as for the
BME280), and a chip model in mock mode can be shared.

SparkFun sells boards whose chips have no driver in its Python list. For the
SHT4x and SHTC3 humidity sensors this provider carries its own drivers, in
SparkFun's style in `src/anolis_qwiic_staging/`, staged to be offered to
SparkFun once proven on hardware; both are supported (`sht4x`, `shtc3`).

| Chip | SparkFun board (this provider) | Adafruit board (adafruit provider) |
| --- | --- | --- |
| BME280 | SEN-15440, SEN-22858 (`bme280`, supported) | Adafruit BME280 (`bme280`, supported) |
| PCA9685 | Servo pHAT DEV-15316, Auto pHAT ROB-16328 | 815, 2327, 3416, 1411, 2928; Motor HAT 2348 (`motor_hat`, supported) |
| NAU7802 | Qwiic Scale SEN-15242 | 4538 |
| SCD4x | SCD41 SEN-22396 | SCD-40 5187, SCD-41 5190, SCD-43 6512 |
| SGP40 | SEN-18345 | 4829 |
| ENS160 | SEN-20844, SEN-22858 | 5606 |
| CCS811 | (link redirects; unconfirmed) | 3566 |
| TMP117 | SEN-15805 | 4821 |
| MCP9600 | SEN-16295 | MCP9601 5165 |
| MCP4725 | BOB-12918 | 935 |
| ADS1015 | DEV-15334 | ADS1x15 boards (numbers unconfirmed) |
| BMP581 | SEN-20170, SEN-20171 | BMP5xx 6407, 6411, 6413 |
| VL53L1X | SEN-14722 | 3967 |
| VCNL4040 | SEN-15177 | 4161 |
| ICM-20948 | Auto pHAT ROB-16328 | 4554 |
| ISM330DHCX | SEN-19764 | 4502, 4569 |
| AS726x | SEN-14347 (AS7262) | 3779 (linked from the AS726x driver) |
| AS7343 | SEN-23220 | 6477 |
| MAX1704x | TOL-20680 | MAX17048 5580 |
| RV-8803 | BOB-16281 | 6538 |
| TCA9548A | BOB-16784 | PCA9548 5626, TCA9548A 2717 |

## Suggested order

Ranked by value per effort for a lab-automation runtime.

Done: **SCMD** (it has a hardware command watchdog: with `FSAFE_TIME` set, a
killed or hung provider stops the motors, which the Adafruit Motor HAT cannot do),
**ADS1015**, **BME280**, **SCD4x**, and the **SHT4x** and **SHTC3** on this
repo's staged drivers.

1. **Qwiic Relay** (four boards, one driver). The clearest safe state there
   is. Confirm the power-on relay state on hardware first.
2. **PCA9685 / Servo pHAT** (DEV-15316). Shares its design with the Adafruit
   servo work; do the function shape once.
3. **Qwiic GPIO** (DEV-17047). Interlocks and simple outputs.
4. **NAU7802** (SEN-15242). Load cell.
5. **MCP9600** thermocouple and **TMP117**. Heater rigs.
6. **TCA9548A mux**. Unlocks duplicate addresses; shares the design decision
   with the Adafruit provider.

Next tier: Qwiic Button (a physical stop input), FS3000 airflow, the Auto
pHAT as a composite of SCMD, PCA9685 and encoder reader.

## How this was counted

Counted on 2026-11-03 from the sources above, fetched fresh; the scripts and
downloads were not kept in this repository, so each method below names what
was read rather than a file to rerun.

| Figure | Value | Method |
| --- | --- | --- |
| Submodules in `Qwiic_Py/.gitmodules` | 60 (51 `drivers/`, 9 `drivers_linux_only/`) | `path` lines in `Qwiic_Py/.gitmodules`, counted per top-level directory |
| Distinct repositories | 59 | submodule URLs compared case-insensitively: one duplicate, the u-blox GPS repository, listed once in each group under different capitalisation |
| Device drivers | 58 | 59 less `qwiic_i2c`, the bus library |
| Licences | 57 MIT, 2 GPL-3.0 (the duplicated u-blox entry), 1 none found (Titan GPS) | each repository's `LICENSE` file, read and classified |
| Drivers whose module accepts `i2c_driver` | 56 of the 57 modules fetched | `grep -q i2c_driver` over each fetched module; the Titan GPS package's `__init__.py` does not mention it (its submodules were not fetched) |
| Products named in README "Supported products" sections | 61 rows | rows in each README's "Supported products" section; READMEs without one fall back to `sparkfun.com/products/N` links, which include host boards (Jetson, Coral) and were filtered by hand |
| Product pages resolved to a SKU | 68 | each linked product page fetched and its `"sku"` field read |

Not counted: SparkFun's whole Qwiic range in the shop. The sparkfun.com/qwiic
page is a curated landing page whose product count and pagination could not be
read from the HTML, so no shop total is given here.
