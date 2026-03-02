"""Tests for netglance.daemon (scheduler, launchd) and the daemon CLI subcommand.

All I/O is mocked -- no real scheduling delays, no real filesystem for plist.
"""

from __future__ import annotations

import plistlib
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from netglance.cli import app
from netglance.daemon.launchd import (
    PLIST_LABEL,
    generate_plist,
    get_plist_path,
    install_plist,
    is_installed,
    uninstall_plist,
)
from netglance.daemon.scheduler import (
    Scheduler,
    ScheduledTask,
    _match_cron_field,
    cron_matches,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Cron matching tests
# ---------------------------------------------------------------------------


class TestMatchCronField:
    """Unit tests for the single-field cron matcher."""

    def test_star_matches_any(self):
        assert _match_cron_field("*", 0) is True
        assert _match_cron_field("*", 59) is True

    def test_step_every_15(self):
        assert _match_cron_field("*/15", 0) is True
        assert _match_cron_field("*/15", 15) is True
        assert _match_cron_field("*/15", 30) is True
        assert _match_cron_field("*/15", 45) is True
        assert _match_cron_field("*/15", 7) is False
        assert _match_cron_field("*/15", 1) is False

    def test_step_every_6(self):
        assert _match_cron_field("*/6", 0) is True
        assert _match_cron_field("*/6", 6) is True
        assert _match_cron_field("*/6", 12) is True
        assert _match_cron_field("*/6", 5) is False

    def test_exact_match(self):
        assert _match_cron_field("30", 30) is True
        assert _match_cron_field("30", 15) is False
        assert _match_cron_field("0", 0) is True
        assert _match_cron_field("0", 1) is False

    def test_invalid_field_returns_false(self):
        assert _match_cron_field("abc", 10) is False
        assert _match_cron_field("*/abc", 10) is False


class TestCronMatches:
    """Integration tests for the full 5-field cron expression matcher."""

    def test_every_15_minutes(self):
        # */15 * * * *
        assert cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 0)) is True
        assert cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 15)) is True
        assert cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 30)) is True
        assert cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 45)) is True
        assert cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 7)) is False

    def test_top_of_hour(self):
        # 0 * * * *
        assert cron_matches("0 * * * *", datetime(2024, 1, 1, 0, 0)) is True
        assert cron_matches("0 * * * *", datetime(2024, 1, 1, 12, 0)) is True
        assert cron_matches("0 * * * *", datetime(2024, 1, 1, 12, 30)) is False

    def test_every_6_hours_at_minute_0(self):
        # 0 */6 * * *
        assert cron_matches("0 */6 * * *", datetime(2024, 1, 1, 0, 0)) is True
        assert cron_matches("0 */6 * * *", datetime(2024, 1, 1, 6, 0)) is True
        assert cron_matches("0 */6 * * *", datetime(2024, 1, 1, 12, 0)) is True
        assert cron_matches("0 */6 * * *", datetime(2024, 1, 1, 18, 0)) is True
        assert cron_matches("0 */6 * * *", datetime(2024, 1, 1, 3, 0)) is False
        assert cron_matches("0 */6 * * *", datetime(2024, 1, 1, 6, 15)) is False

    def test_daily_at_2am(self):
        # 0 2 * * *
        assert cron_matches("0 2 * * *", datetime(2024, 1, 1, 2, 0)) is True
        assert cron_matches("0 2 * * *", datetime(2024, 1, 1, 3, 0)) is False
        assert cron_matches("0 2 * * *", datetime(2024, 1, 1, 2, 1)) is False

    def test_daily_at_7am(self):
        # 0 7 * * *
        assert cron_matches("0 7 * * *", datetime(2024, 6, 15, 7, 0)) is True
        assert cron_matches("0 7 * * *", datetime(2024, 6, 15, 8, 0)) is False

    def test_specific_day_of_month(self):
        # 0 0 15 * *  -> midnight on the 15th
        assert cron_matches("0 0 15 * *", datetime(2024, 3, 15, 0, 0)) is True
        assert cron_matches("0 0 15 * *", datetime(2024, 3, 14, 0, 0)) is False

    def test_specific_month(self):
        # 0 0 1 6 *  -> midnight on June 1st
        assert cron_matches("0 0 1 6 *", datetime(2024, 6, 1, 0, 0)) is True
        assert cron_matches("0 0 1 6 *", datetime(2024, 7, 1, 0, 0)) is False

    def test_day_of_week(self):
        # 0 9 * * 0  -> 9am on Monday (Python weekday 0=Monday)
        # 2024-01-01 is a Monday
        assert cron_matches("0 9 * * 0", datetime(2024, 1, 1, 9, 0)) is True
        # 2024-01-02 is a Tuesday
        assert cron_matches("0 9 * * 0", datetime(2024, 1, 2, 9, 0)) is False

    def test_all_stars(self):
        assert cron_matches("* * * * *", datetime(2024, 6, 15, 14, 33)) is True

    def test_invalid_expression_returns_false(self):
        assert cron_matches("only three fields", datetime(2024, 1, 1, 0, 0)) is False
        assert cron_matches("", datetime(2024, 1, 1, 0, 0)) is False


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------


class TestScheduledTask:
    """Basic tests for the ScheduledTask dataclass."""

    def test_defaults(self):
        task = ScheduledTask(name="test", cron_expr="* * * * *", callback=lambda: None)
        assert task.last_run is None
        assert task.enabled is True

    def test_fields(self):
        cb = MagicMock()
        task = ScheduledTask(
            name="dns", cron_expr="0 * * * *", callback=cb, enabled=False
        )
        assert task.name == "dns"
        assert task.cron_expr == "0 * * * *"
        assert task.enabled is False
        assert task.callback is cb


class TestScheduler:
    """Tests for the Scheduler class with injected time functions."""

    def test_add_and_remove_task(self):
        scheduler = Scheduler()
        task = ScheduledTask(name="a", cron_expr="* * * * *", callback=lambda: None)
        scheduler.add_task(task)
        assert len(scheduler._tasks) == 1

        scheduler.remove_task("a")
        assert len(scheduler._tasks) == 0

    def test_remove_nonexistent_is_silent(self):
        scheduler = Scheduler()
        scheduler.remove_task("nope")  # should not raise
        assert len(scheduler._tasks) == 0

    def test_should_run_basic(self):
        now = datetime(2024, 1, 1, 0, 0)  # minute=0
        scheduler = Scheduler()
        task = ScheduledTask(name="t", cron_expr="*/15 * * * *", callback=lambda: None)

        assert scheduler._should_run(task, now) is True

    def test_should_run_disabled_task(self):
        now = datetime(2024, 1, 1, 0, 0)
        scheduler = Scheduler()
        task = ScheduledTask(
            name="t", cron_expr="* * * * *", callback=lambda: None, enabled=False
        )

        assert scheduler._should_run(task, now) is False

    def test_should_run_prevents_double_run_same_minute(self):
        now = datetime(2024, 1, 1, 0, 0)
        scheduler = Scheduler()
        task = ScheduledTask(
            name="t", cron_expr="* * * * *", callback=lambda: None, last_run=now
        )

        assert scheduler._should_run(task, now) is False

    def test_should_run_allows_next_minute(self):
        scheduler = Scheduler()
        task = ScheduledTask(
            name="t",
            cron_expr="* * * * *",
            callback=lambda: None,
            last_run=datetime(2024, 1, 1, 0, 0),
        )

        assert scheduler._should_run(task, datetime(2024, 1, 1, 0, 1)) is True

    def test_should_run_cron_mismatch(self):
        now = datetime(2024, 1, 1, 0, 7)  # minute=7 doesn't match */15
        scheduler = Scheduler()
        task = ScheduledTask(name="t", cron_expr="*/15 * * * *", callback=lambda: None)

        assert scheduler._should_run(task, now) is False

    def test_start_stop_lifecycle(self):
        """Start in non-blocking mode, verify it runs, then stop."""
        call_count = 0
        now = datetime(2024, 1, 1, 0, 0)

        def _fake_sleep(secs: float) -> None:
            nonlocal call_count
            call_count += 1
            # Stop after first iteration
            scheduler.stop()

        scheduler = Scheduler(_now_fn=lambda: now, _sleep_fn=_fake_sleep)
        cb = MagicMock()
        scheduler.add_task(
            ScheduledTask(name="t", cron_expr="* * * * *", callback=cb)
        )
        scheduler.start(blocking=False)
        # Wait for the thread to finish
        if scheduler._thread:
            scheduler._thread.join(timeout=5)

        cb.assert_called_once()
        assert call_count >= 1

    def test_start_blocking_runs_until_stop(self):
        """Blocking start runs the loop; we stop it via the sleep function."""
        iterations = 0

        def _fake_sleep(secs: float) -> None:
            nonlocal iterations
            iterations += 1
            if iterations >= 2:
                scheduler.stop()

        scheduler = Scheduler(
            _now_fn=lambda: datetime(2024, 1, 1, 0, 0), _sleep_fn=_fake_sleep
        )
        scheduler.add_task(
            ScheduledTask(name="t", cron_expr="* * * * *", callback=lambda: None)
        )
        scheduler.start(blocking=True)

        assert iterations >= 2

    def test_callback_exception_does_not_crash_scheduler(self):
        """If a task callback raises, the scheduler should continue."""
        call_log: list[str] = []

        def _bad_callback():
            call_log.append("bad")
            raise ValueError("oops")

        def _good_callback():
            call_log.append("good")

        iteration = 0

        def _fake_sleep(secs: float) -> None:
            nonlocal iteration
            iteration += 1
            if iteration >= 1:
                scheduler.stop()

        scheduler = Scheduler(
            _now_fn=lambda: datetime(2024, 1, 1, 0, 0), _sleep_fn=_fake_sleep
        )
        scheduler.add_task(
            ScheduledTask(name="bad", cron_expr="* * * * *", callback=_bad_callback)
        )
        scheduler.add_task(
            ScheduledTask(name="good", cron_expr="* * * * *", callback=_good_callback)
        )
        scheduler.start(blocking=True)

        assert "bad" in call_log
        assert "good" in call_log

    def test_get_status(self):
        scheduler = Scheduler()
        now = datetime(2024, 1, 15, 10, 30)
        scheduler.add_task(
            ScheduledTask(
                name="discover",
                cron_expr="*/15 * * * *",
                callback=lambda: None,
                last_run=now,
            )
        )
        scheduler.add_task(
            ScheduledTask(
                name="dns", cron_expr="0 * * * *", callback=lambda: None
            )
        )

        status = scheduler.get_status()
        assert len(status) == 2
        assert status[0]["name"] == "discover"
        assert status[0]["cron_expr"] == "*/15 * * * *"
        assert status[0]["enabled"] is True
        assert status[0]["last_run"] == now.isoformat()
        assert status[1]["name"] == "dns"
        assert status[1]["last_run"] is None

    def test_get_status_empty(self):
        scheduler = Scheduler()
        assert scheduler.get_status() == []


# ---------------------------------------------------------------------------
# Launchd tests
# ---------------------------------------------------------------------------


class TestGeneratePlist:
    """Tests for plist dict generation."""

    def test_structure(self):
        plist = generate_plist(netglance_path="/usr/local/bin/netglance")
        assert plist["Label"] == PLIST_LABEL
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] is True
        assert "StandardOutPath" in plist
        assert "StandardErrorPath" in plist
        assert "WorkingDirectory" in plist

    def test_program_arguments(self):
        plist = generate_plist(netglance_path="/usr/local/bin/netglance")
        args = plist["ProgramArguments"]
        assert args[0] == "/usr/local/bin/netglance"
        assert "daemon" in args
        assert "start" in args

    def test_custom_config_path(self):
        plist = generate_plist(
            netglance_path="/usr/local/bin/netglance",
            config_path="/etc/netglance/config.yaml",
        )
        args = plist["ProgramArguments"]
        assert "--config" in args
        assert "/etc/netglance/config.yaml" in args

    def test_no_config_means_no_config_flag(self):
        plist = generate_plist(netglance_path="/usr/local/bin/netglance")
        args = plist["ProgramArguments"]
        assert "--config" not in args

    def test_auto_detect_path(self):
        """When no netglance_path is given, it auto-detects."""
        plist = generate_plist()
        # Should have some string as the first argument
        assert isinstance(plist["ProgramArguments"][0], str)
        assert len(plist["ProgramArguments"][0]) > 0

    def test_log_path_in_config_dir(self):
        plist = generate_plist(netglance_path="/usr/local/bin/netglance")
        assert ".config/netglance" in plist["StandardOutPath"]
        assert ".config/netglance" in plist["StandardErrorPath"]

    def test_working_directory_is_home(self):
        plist = generate_plist(netglance_path="/usr/local/bin/netglance")
        assert plist["WorkingDirectory"] == str(Path.home())


class TestInstallPlist:
    """Tests for plist installation using tmp_path."""

    def test_install_creates_file(self, tmp_path):
        plist_dir = tmp_path / "LaunchAgents"
        log_dir = tmp_path / "logs"

        path = install_plist(
            netglance_path="/usr/local/bin/netglance",
            _plist_dir=plist_dir,
            _log_dir=log_dir,
        )

        assert path.exists()
        assert path.name == f"{PLIST_LABEL}.plist"
        assert plist_dir.exists()
        assert log_dir.exists()

    def test_install_writes_valid_plist(self, tmp_path):
        plist_dir = tmp_path / "LaunchAgents"
        log_dir = tmp_path / "logs"

        path = install_plist(
            netglance_path="/usr/local/bin/netglance",
            _plist_dir=plist_dir,
            _log_dir=log_dir,
        )

        with open(path, "rb") as fp:
            data = plistlib.load(fp)

        assert data["Label"] == PLIST_LABEL
        assert data["RunAtLoad"] is True
        assert data["ProgramArguments"][0] == "/usr/local/bin/netglance"

    def test_install_creates_directories(self, tmp_path):
        plist_dir = tmp_path / "deep" / "nested" / "LaunchAgents"
        log_dir = tmp_path / "deep" / "nested" / "logs"

        install_plist(
            netglance_path="/usr/local/bin/netglance",
            _plist_dir=plist_dir,
            _log_dir=log_dir,
        )

        assert plist_dir.exists()
        assert log_dir.exists()


class TestUninstallPlist:
    """Tests for plist uninstallation using tmp_path."""

    def test_uninstall_removes_file(self, tmp_path):
        plist_dir = tmp_path / "LaunchAgents"
        log_dir = tmp_path / "logs"

        install_plist(
            netglance_path="/usr/local/bin/netglance",
            _plist_dir=plist_dir,
            _log_dir=log_dir,
        )

        result = uninstall_plist(_plist_dir=plist_dir)
        assert result is True
        assert not (plist_dir / f"{PLIST_LABEL}.plist").exists()

    def test_uninstall_returns_false_when_not_installed(self, tmp_path):
        plist_dir = tmp_path / "LaunchAgents"
        plist_dir.mkdir(parents=True)

        result = uninstall_plist(_plist_dir=plist_dir)
        assert result is False


class TestIsInstalled:
    """Tests for is_installed check."""

    def test_returns_true_when_installed(self, tmp_path):
        plist_dir = tmp_path / "LaunchAgents"
        log_dir = tmp_path / "logs"
        install_plist(
            netglance_path="/usr/local/bin/netglance",
            _plist_dir=plist_dir,
            _log_dir=log_dir,
        )

        assert is_installed(_plist_dir=plist_dir) is True

    def test_returns_false_when_not_installed(self, tmp_path):
        plist_dir = tmp_path / "LaunchAgents"
        plist_dir.mkdir(parents=True)

        assert is_installed(_plist_dir=plist_dir) is False

    def test_returns_false_when_dir_missing(self, tmp_path):
        plist_dir = tmp_path / "nonexistent"

        assert is_installed(_plist_dir=plist_dir) is False


class TestGetPlistPath:
    """Test the plist path helper."""

    def test_returns_path_object(self):
        path = get_plist_path()
        assert isinstance(path, Path)
        assert PLIST_LABEL in path.name


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestDaemonCli:
    """Tests for the daemon CLI subcommand group."""

    def test_help(self):
        result = runner.invoke(app, ["daemon", "--help"])
        assert result.exit_code == 0
        assert "daemon" in result.output.lower() or "Background" in result.output

    def test_help_shows_subcommands(self):
        result = runner.invoke(app, ["daemon", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "install" in result.output
        assert "uninstall" in result.output
        assert "status" in result.output

    def test_status_when_not_installed(self):
        with patch(
            "netglance.cli.daemon.is_installed", return_value=False
        ), patch(
            "netglance.cli.daemon.get_plist_path",
            return_value=Path("/fake/path.plist"),
        ):
            result = runner.invoke(app, ["daemon", "status"])
            assert result.exit_code == 0
            assert "not installed" in result.output.lower()

    def test_status_when_installed(self):
        with patch(
            "netglance.cli.daemon.is_installed", return_value=True
        ), patch(
            "netglance.cli.daemon.get_plist_path",
            return_value=Path("/fake/LaunchAgents/com.netglance.daemon.plist"),
        ):
            result = runner.invoke(app, ["daemon", "status"])
            assert result.exit_code == 0
            assert "installed" in result.output.lower()

    def test_status_shows_schedules(self):
        with patch(
            "netglance.cli.daemon.is_installed", return_value=False
        ), patch(
            "netglance.cli.daemon.get_plist_path",
            return_value=Path("/fake/path.plist"),
        ):
            result = runner.invoke(app, ["daemon", "status"])
            assert result.exit_code == 0
            assert "discover" in result.output
            assert "dns_check" in result.output

    def test_install(self):
        mock_path = Path("/fake/LaunchAgents/com.netglance.daemon.plist")
        with patch(
            "netglance.cli.daemon.install_plist", return_value=mock_path
        ) as mock_install:
            result = runner.invoke(app, ["daemon", "install"])
            assert result.exit_code == 0
            mock_install.assert_called_once()
            assert "installed" in result.output.lower()

    def test_install_with_options(self):
        mock_path = Path("/fake/LaunchAgents/com.netglance.daemon.plist")
        with patch(
            "netglance.cli.daemon.install_plist", return_value=mock_path
        ) as mock_install:
            result = runner.invoke(
                app,
                [
                    "daemon",
                    "install",
                    "--netglance-path",
                    "/opt/bin/netglance",
                    "--config",
                    "/etc/netglance.yaml",
                ],
            )
            assert result.exit_code == 0
            mock_install.assert_called_once_with(
                netglance_path="/opt/bin/netglance", config_path="/etc/netglance.yaml"
            )

    def test_uninstall_when_installed(self):
        with patch(
            "netglance.cli.daemon.uninstall_plist", return_value=True
        ) as mock_uninstall:
            result = runner.invoke(app, ["daemon", "uninstall"])
            assert result.exit_code == 0
            mock_uninstall.assert_called_once()
            assert "removed" in result.output.lower()

    def test_uninstall_when_not_installed(self):
        with patch(
            "netglance.cli.daemon.uninstall_plist", return_value=False
        ):
            result = runner.invoke(app, ["daemon", "uninstall"])
            assert result.exit_code == 0
            assert "not found" in result.output.lower()
