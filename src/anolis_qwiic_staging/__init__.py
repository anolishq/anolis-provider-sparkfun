"""Qwiic Python drivers written for this provider, staged to go upstream.

SparkFun's Qwiic Python package has no driver for some chips on SparkFun
boards. Each module here is such a driver, written in SparkFun's own driver
conventions (a ``Qwiic<Chip>`` class taking ``address`` and ``i2c_driver``,
``available_addresses``, ``is_connected()``, ``begin()``) and using only the
``qwiic_i2c`` bus interface, so it can be offered to SparkFun as it stands.

**Staged for upstream.** Once a module here has run on real hardware, it is
offered to SparkFun as a Qwiic Python driver; when SparkFun publishes it, the
provider switches to the published package and the module is deleted from
here. Nothing in this package may import from the provider.

- ``qwiic_sht4x``: Sensirion SHT40, SHT41, SHT45.
- ``qwiic_shtc3``: Sensirion SHTC3.
"""
