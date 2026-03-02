"""Smoke tests for the scaffold."""

from typer.testing import CliRunner

from netglance import __version__
from netglance.cli import app
from netglance.config.settings import Settings
from netglance.store.db import Store

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "netglance" in result.output.lower()


def test_store_round_trip(tmp_db: Store):
    row_id = tmp_db.save_result("test_module", {"key": "value"})
    assert row_id is not None
    results = tmp_db.get_results("test_module")
    assert len(results) == 1
    assert results[0]["key"] == "value"


def test_baseline_round_trip(tmp_db: Store):
    bid = tmp_db.save_baseline({"devices": []}, label="test")
    assert bid is not None
    baseline = tmp_db.get_latest_baseline()
    assert baseline is not None
    assert baseline["devices"] == []


def test_settings_defaults(tmp_config):
    settings = Settings.load(tmp_config)
    assert settings.network.subnet == "192.168.1.0/24"
    assert settings.network.gateway == "192.168.1.1"


def test_settings_from_yaml(tmp_config):
    tmp_config.write_text("network:\n  subnet: 10.0.0.0/24\n  gateway: 10.0.0.1\n")
    settings = Settings.load(tmp_config)
    assert settings.network.subnet == "10.0.0.0/24"
    assert settings.network.gateway == "10.0.0.1"
