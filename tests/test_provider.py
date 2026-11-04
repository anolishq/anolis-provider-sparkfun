"""The provider in mock mode: inventory, config, and losing and regaining a board."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from anolis_provider_sdk import DeviceState, HealthState, ProviderError, StatusCode
from anolis_provider_sdk.cli import ConfigError, load_config

from anolis_provider_sparkfun.devices.scmd import SCMD
from anolis_provider_sparkfun.mock import FakeQwiicBus, FakeSCMD
from anolis_provider_sparkfun.provider import SparkFunProvider, bus_device, open_bus

ALL_SIGNALS = ["motor_a_throttle", "motor_b_throttle", "failsafe_trips"]


def started(config: dict[str, Any]) -> SparkFunProvider:
    provider = SparkFunProvider(config)
    provider.start(0.0)
    return provider


def mock(*devices: dict[str, Any]) -> dict[str, Any]:
    return {"mock": True, "devices": list(devices) or [{"id": "drive0", "type": "scmd"}]}


def bus(provider: SparkFunProvider) -> FakeQwiicBus:
    fake = provider._bus
    assert isinstance(fake, FakeQwiicBus)
    return fake


def test_devices_come_from_the_config_with_their_address() -> None:
    p = started(mock({"id": "drive0", "type": "scmd"}, {"id": "drive1", "type": "scmd", "address": 0x58}))
    assert [(d.id, d.type.id, d.address) for d in p.devices()] == [
        ("drive0", "scmd", "i2c-1:0x5d"),
        ("drive1", "scmd", "i2c-1:0x58"),
    ]


def test_read_returns_every_signal_asked_for() -> None:
    p = started(mock())
    assert p.read(p.devices()[0], ALL_SIGNALS) == {
        "motor_a_throttle": 0.0,
        "motor_b_throttle": 0.0,
        "failsafe_trips": 0,
    }


def test_options_reach_the_driver_with_their_defaults() -> None:
    p = started(
        mock({"id": "drive0", "type": "scmd"}, {"id": "drive1", "type": "scmd", "address": 0x58, "failsafe_ms": 0})
    )
    first, second = bus(p).chips[0x5D], bus(p).chips[0x58]
    assert isinstance(first, FakeSCMD) and isinstance(second, FakeSCMD)
    assert first.registers[FakeSCMD.FSAFE_TIME] == 200
    assert second.registers[FakeSCMD.FSAFE_TIME] == 0


def test_a_board_that_stops_answering_is_unreachable_then_recovers() -> None:
    p = started(mock())
    d = p.devices()[0]
    bus(p).fail = True
    with pytest.raises(ProviderError) as err:
        p.read(d, ["motor_a_throttle"])
    assert err.value.code is StatusCode.UNAVAILABLE
    health = p.device_health(d)
    assert health and health.state is DeviceState.UNREACHABLE
    assert p.health().state is HealthState.DEGRADED
    # Still down: the retry on the next read fails the same way.
    with pytest.raises(ProviderError):
        p.read(d, ["motor_a_throttle"])
    bus(p).fail = False
    assert p.read(d, ["motor_a_throttle"]) == {"motor_a_throttle": 0.0}
    assert p.device_health(d) is None
    assert p.health().state is HealthState.OK


def test_a_board_missing_at_start_is_listed_and_unreachable() -> None:
    p = SparkFunProvider(mock())
    original = FakeQwiicBus.__init__

    def empty_bus(self: FakeQwiicBus, chips: Any) -> None:
        original(self, {})

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FakeQwiicBus, "__init__", empty_bus)
        p.start(0.0)
    d = p.devices()[0]
    health = p.device_health(d)
    assert health and health.state is DeviceState.UNREACHABLE
    assert "0x5d" in health.message
    with pytest.raises(ProviderError) as err:
        p.read(d, ["motor_a_throttle"])
    assert err.value.code is StatusCode.UNAVAILABLE


def test_health_is_ok_before_start() -> None:
    p = SparkFunProvider(mock())
    assert p.health().state is HealthState.OK
    assert p.device_health(p.devices()[0]) is None


@pytest.mark.parametrize(
    ("devices", "message"),
    [
        ([{"id": "a", "type": "scmd"}, {"id": "a", "type": "scmd", "address": 0x58}], "configured twice"),
        ([{"id": "a", "type": "scmd"}, {"id": "b", "type": "scmd", "address": 0x5D}], "0x5d"),
    ],
)
def test_conflicting_devices_are_refused(devices: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SparkFunProvider({"mock": True, "devices": devices})


@pytest.mark.parametrize(
    "body",
    [
        "devices: []",
        "devices: [{id: drive0, type: scmd, address: 0x62}]",
        "devices: [{id: drive0, type: bme280}]",
        "devices: [{id: Drive0, type: scmd}]",
        "i2c_bus: -1\ndevices: [{id: drive0, type: scmd}]",
        "devices: [{id: drive0, type: scmd}]\nextra: 1",
        "devices: [{id: drive0, type: scmd, failsafe_ms: 2560}]",
        "devices: [{id: drive0, type: scmd, failsafe_ms: 15}]",
        "devices: [{id: drive0, type: scmd, failsafe_ms: -10}]",
    ],
)
def test_the_schema_rejects_bad_configs(tmp_path: Path, body: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(body)
    with pytest.raises(ConfigError):
        load_config(SparkFunProvider, str(path))


def test_check_host_needs_nothing_in_mock_mode() -> None:
    assert SparkFunProvider.check_host(mock()) == []


REAL = {"i2c_bus": 3, "devices": [{"id": "drive0", "type": "scmd"}]}


def check_host_with_node(monkeypatch: pytest.MonkeyPatch, node: Path) -> Any:
    def fake_bus_device(bus: int) -> str:
        assert bus == 3
        return str(node)

    monkeypatch.setattr("anolis_provider_sparkfun.provider.bus_device", fake_bus_device)
    [req] = SparkFunProvider.check_host(REAL)
    assert req.id == "i2c_bus"
    return req


def test_check_host_reports_a_missing_bus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    req = check_host_with_node(monkeypatch, tmp_path / "i2c-3")
    assert req.status == "unmet"
    assert "does not exist" in req.detail
    assert "raspi-config" in req.remedy


def test_check_host_reports_a_bus_the_user_cannot_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    node = tmp_path / "i2c-3"
    node.touch(mode=0o000)
    if os.access(node, os.R_OK):
        pytest.skip("running as root: file permissions do not apply")
    req = check_host_with_node(monkeypatch, node)
    assert req.status == "unmet"
    assert "not readable and writable" in req.detail
    assert "i2c group" in req.remedy


def test_check_host_accepts_an_accessible_bus(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    node = tmp_path / "i2c-3"
    node.touch(mode=0o600)
    assert check_host_with_node(monkeypatch, node).status == "met"


def test_the_bus_device_node_follows_the_bus_number() -> None:
    assert bus_device(1) == "/dev/i2c-1"


def test_an_error_that_is_not_a_bus_error_fails_start_instead_of_hiding_as_unreachable() -> None:
    # A frozen build missing a data file fails like this: it is a provider fault,
    # and reporting the board as merely unreachable would hide it.
    p = SparkFunProvider(mock())

    def broken(self: Any, i2c: Any, address: int, options: Any) -> None:
        raise FileNotFoundError(2, "No such file or directory", "some_data_file.json")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SCMD, "__init__", broken)
        with pytest.raises(FileNotFoundError):
            p.start(0.0)


def test_an_error_that_is_not_a_bus_error_on_read_is_not_unreachable() -> None:
    p = started(mock())
    d = p.devices()[0]

    def broken(self: Any, signal_ids: list[str]) -> Any:
        raise PermissionError(13, "Permission denied")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(SCMD, "read", broken)
        with pytest.raises(PermissionError):
            p.read(d, ["motor_a_throttle"])
    assert p.device_health(d) is None


def test_the_real_bus_opens_the_configured_bus_number(monkeypatch: pytest.MonkeyPatch) -> None:
    # SparkFun's unreleased qwiic_i2c drops iBus and picks the bus from the board
    # model; this fails if an upgrade brings that in.
    opened: list[int] = []

    class FakeSMBus:
        def __init__(self, bus: int) -> None:
            opened.append(bus)

    monkeypatch.setattr("smbus2.SMBus", FakeSMBus)
    open_bus(3)
    assert opened == [3]


def test_a_bus_that_will_not_open_fails_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(bus: int) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("smbus2.SMBus", refuse)
    with pytest.raises(OSError, match="/dev/i2c-3"):
        open_bus(3)


def test_a_board_refuses_another_boards_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import jsonschema

    from anolis_provider_sparkfun import devices, provider

    class Sensor(SCMD):
        options = {}

    monkeypatch.setitem(devices.KINDS, "sensor", Sensor)
    schema = provider._device_schema()
    jsonschema.validate({"id": "s", "type": "scmd", "failsafe_ms": 100}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"id": "s", "type": "sensor", "failsafe_ms": 100}, schema)
