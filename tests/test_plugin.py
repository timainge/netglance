"""Tests for netglance plugin system."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from netglance.plugins.base import BasePlugin, NetglancePlugin
from netglance.plugins.loader import (
    _find_plugin_class,
    _import_module_from_path,
    discover_plugins,
    get_plugin_checks,
    load_all_plugins,
    load_plugin,
    register_plugin_commands,
)
from netglance.store.models import CheckStatus, PluginInfo

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers — minimal plugin implementations used across tests
# ---------------------------------------------------------------------------


class MinimalPlugin:
    """A bare Protocol-compliant plugin (no BasePlugin inheritance)."""

    @property
    def name(self) -> str:
        return "minimal"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "A minimal test plugin"

    def check(self) -> CheckStatus:
        return CheckStatus(module=self.name, status="pass", summary="All good")

    def cli_app(self) -> typer.Typer | None:
        return None


class PluginWithCLI(BasePlugin):
    """A BasePlugin subclass that provides a CLI sub-app."""

    name = "with-cli"
    version = "2.0.0"
    description = "Plugin with CLI commands"

    def check(self) -> CheckStatus:
        return CheckStatus(module=self.name, status="pass", summary="CLI plugin OK")

    def cli_app(self) -> typer.Typer | None:
        sub = typer.Typer(help="With-CLI plugin commands.")

        @sub.command("hello")
        def hello():
            """Say hello."""
            print("hello from with-cli plugin")

        return sub


class BrokenCheckPlugin(BasePlugin):
    """Plugin whose check() raises an exception."""

    name = "broken"
    version = "0.1.0"
    description = "Broken check plugin"

    def check(self) -> CheckStatus:
        raise RuntimeError("Something went wrong")


def _make_module(plugin_class: type, module_name: str = "fake_plugin") -> types.ModuleType:
    """Create a fake module containing *plugin_class*."""
    mod = types.ModuleType(module_name)
    mod.__name__ = module_name
    plugin_class.__module__ = module_name
    setattr(mod, plugin_class.__name__, plugin_class)
    return mod


# ---------------------------------------------------------------------------
# NetglancePlugin Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    def test_minimal_plugin_satisfies_protocol(self):
        p = MinimalPlugin()
        assert isinstance(p, NetglancePlugin)

    def test_base_plugin_satisfies_protocol(self):
        p = BasePlugin()
        assert isinstance(p, NetglancePlugin)

    def test_plugin_with_cli_satisfies_protocol(self):
        p = PluginWithCLI()
        assert isinstance(p, NetglancePlugin)

    def test_plain_object_does_not_satisfy_protocol(self):
        class NotAPlugin:
            pass

        assert not isinstance(NotAPlugin(), NetglancePlugin)

    def test_partial_protocol_not_satisfied(self):
        """Missing methods → not a valid plugin."""

        class Partial:
            @property
            def name(self):
                return "x"

        assert not isinstance(Partial(), NetglancePlugin)


# ---------------------------------------------------------------------------
# BasePlugin defaults
# ---------------------------------------------------------------------------


class TestBasePlugin:
    def test_default_name(self):
        assert BasePlugin.name == "unnamed"

    def test_default_version(self):
        assert BasePlugin.version == "0.0.0"

    def test_default_description(self):
        assert BasePlugin.description == ""

    def test_default_check_returns_skip(self):
        p = BasePlugin()
        result = p.check()
        assert result.status == "skip"
        assert result.module == "unnamed"
        assert "No check implemented" in result.summary

    def test_default_cli_app_returns_none(self):
        p = BasePlugin()
        assert p.cli_app() is None

    def test_subclass_overrides_name(self):
        class MyPlugin(BasePlugin):
            name = "my-plugin"

        assert MyPlugin().name == "my-plugin"

    def test_subclass_check_override(self):
        class MyPlugin(BasePlugin):
            name = "custom"

            def check(self) -> CheckStatus:
                return CheckStatus(module=self.name, status="pass", summary="OK")

        assert MyPlugin().check().status == "pass"


# ---------------------------------------------------------------------------
# _find_plugin_class
# ---------------------------------------------------------------------------


class TestFindPluginClass:
    def test_finds_minimal_plugin(self):
        mod = _make_module(MinimalPlugin, "mod_minimal")
        cls = _find_plugin_class(mod)
        assert cls is MinimalPlugin

    def test_finds_base_plugin_subclass(self):
        mod = _make_module(PluginWithCLI, "mod_withcli")
        cls = _find_plugin_class(mod)
        assert cls is PluginWithCLI

    def test_returns_none_for_empty_module(self):
        mod = types.ModuleType("empty_mod")
        mod.__name__ = "empty_mod"
        cls = _find_plugin_class(mod)
        assert cls is None

    def test_ignores_base_plugin_itself(self):
        mod = types.ModuleType("base_mod")
        mod.__name__ = "base_mod"
        BasePlugin.__module__ = "base_mod"
        mod.BasePlugin = BasePlugin
        # Should NOT return BasePlugin
        cls = _find_plugin_class(mod)
        assert cls is not BasePlugin

    def test_ignores_imported_classes(self):
        """Classes whose __module__ != module.__name__ are skipped."""
        mod = types.ModuleType("importer_mod")
        mod.__name__ = "importer_mod"
        # MinimalPlugin's __module__ won't match "importer_mod"
        MinimalPlugin.__module__ = "some_other_mod"
        mod.MinimalPlugin = MinimalPlugin
        cls = _find_plugin_class(mod)
        assert cls is None


# ---------------------------------------------------------------------------
# load_plugin
# ---------------------------------------------------------------------------


class TestLoadPlugin:
    def test_load_valid_plugin(self, tmp_path):
        plugin_file = tmp_path / "good_plugin.py"

        def fake_import(path):
            mod = _make_module(MinimalPlugin, "fake_minimal")
            return mod

        plugin = load_plugin(plugin_file, _import_fn=fake_import)
        assert plugin is not None
        assert plugin.name == "minimal"

    def test_load_returns_none_on_import_error(self, tmp_path):
        plugin_file = tmp_path / "bad_plugin.py"

        def fake_import(path):
            return None

        plugin = load_plugin(plugin_file, _import_fn=fake_import)
        assert plugin is None

    def test_load_returns_none_if_no_class_found(self, tmp_path):
        plugin_file = tmp_path / "empty_plugin.py"

        def fake_import(path):
            mod = types.ModuleType("empty_plugin")
            mod.__name__ = "empty_plugin"
            return mod

        plugin = load_plugin(plugin_file, _import_fn=fake_import)
        assert plugin is None

    def test_load_plugin_instantiation_error(self, tmp_path):
        plugin_file = tmp_path / "broken_init.py"

        class BadInit(BasePlugin):
            name = "bad-init"
            version = "0.0.1"
            description = "Fails on init"

            def __init__(self):
                raise ValueError("Init failure")

        def fake_import(path):
            mod = _make_module(BadInit, "bad_init_mod")
            return mod

        plugin = load_plugin(plugin_file, _import_fn=fake_import)
        assert plugin is None


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------


class TestDiscoverPlugins:
    def test_returns_empty_if_dir_not_exist(self, tmp_path):
        nonexistent = tmp_path / "no_such_dir"
        result = discover_plugins(nonexistent)
        assert result == []

    def test_discovers_single_plugin(self, tmp_path):
        plugin_file = tmp_path / "myplugin.py"
        plugin_file.touch()

        def fake_listdir(d):
            return [plugin_file]

        def fake_import(path):
            return _make_module(MinimalPlugin, "mod_minimal")

        infos = discover_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert len(infos) == 1
        assert infos[0].name == "minimal"
        assert infos[0].version == "1.0.0"
        assert infos[0].module_path == str(plugin_file)

    def test_skips_underscore_files(self, tmp_path):
        dunder_file = tmp_path / "__init__.py"
        dunder_file.touch()

        called_with = []

        def fake_listdir(d):
            return [dunder_file]

        def fake_import(path):
            called_with.append(path)
            return None

        discover_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert called_with == []

    def test_skips_files_with_no_plugin_class(self, tmp_path):
        plain_file = tmp_path / "notaplugin.py"
        plain_file.touch()

        def fake_listdir(d):
            return [plain_file]

        def fake_import(path):
            mod = types.ModuleType("not_a_plugin")
            mod.__name__ = "not_a_plugin"
            return mod

        infos = discover_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert infos == []

    def test_skips_failed_imports(self, tmp_path):
        bad_file = tmp_path / "bad.py"
        bad_file.touch()

        def fake_listdir(d):
            return [bad_file]

        def fake_import(path):
            return None

        infos = discover_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert infos == []

    def test_discovers_plugin_commands(self, tmp_path):
        plugin_file = tmp_path / "withcli.py"
        plugin_file.touch()

        def fake_listdir(d):
            return [plugin_file]

        def fake_import(path):
            return _make_module(PluginWithCLI, "mod_withcli")

        infos = discover_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert len(infos) == 1
        assert "hello" in infos[0].commands

    def test_discovers_multiple_plugins(self, tmp_path):
        file1 = tmp_path / "plugin1.py"
        file2 = tmp_path / "plugin2.py"
        file1.touch()
        file2.touch()

        modules = [
            _make_module(MinimalPlugin, "mod1"),
            _make_module(PluginWithCLI, "mod2"),
        ]
        idx = [0]

        def fake_listdir(d):
            return [file1, file2]

        def fake_import(path):
            mod = modules[idx[0]]
            idx[0] += 1
            return mod

        infos = discover_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert len(infos) == 2


# ---------------------------------------------------------------------------
# load_all_plugins
# ---------------------------------------------------------------------------


class TestLoadAllPlugins:
    def test_returns_empty_if_dir_not_exist(self, tmp_path):
        result = load_all_plugins(tmp_path / "nonexistent")
        assert result == []

    def test_loads_single_plugin(self, tmp_path):
        plugin_file = tmp_path / "myplugin.py"
        plugin_file.touch()

        def fake_listdir(d):
            return [plugin_file]

        def fake_import(path):
            return _make_module(MinimalPlugin, "load_all_mod1")

        plugins = load_all_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert len(plugins) == 1
        assert plugins[0].name == "minimal"

    def test_skips_failed_loads(self, tmp_path):
        file1 = tmp_path / "good.py"
        file2 = tmp_path / "bad.py"
        file1.touch()
        file2.touch()

        calls = [0]

        def fake_listdir(d):
            return [file1, file2]

        def fake_import(path):
            call_idx = calls[0]
            calls[0] += 1
            if call_idx == 0:
                return _make_module(MinimalPlugin, "load_all_good")
            return None  # second import fails

        plugins = load_all_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert len(plugins) == 1

    def test_skips_underscore_files(self, tmp_path):
        private = tmp_path / "_private.py"
        private.touch()

        called = []

        def fake_listdir(d):
            return [private]

        def fake_import(path):
            called.append(path)
            return None

        load_all_plugins(tmp_path, _listdir_fn=fake_listdir, _import_fn=fake_import)
        assert called == []


# ---------------------------------------------------------------------------
# register_plugin_commands
# ---------------------------------------------------------------------------


class TestRegisterPluginCommands:
    def test_registers_plugin_with_cli(self):
        root_app = typer.Typer()
        plugin = PluginWithCLI()
        register_plugin_commands(root_app, [plugin])
        names = [g.name for g in root_app.registered_groups]
        assert "plugin-with-cli" in names

    def test_skips_plugin_without_cli(self):
        root_app = typer.Typer()
        plugin = MinimalPlugin()  # cli_app() returns None
        register_plugin_commands(root_app, [plugin])
        assert root_app.registered_groups == []

    def test_handles_cli_app_exception(self):
        class BadCLIPlugin(BasePlugin):
            name = "bad-cli"
            version = "0.0.1"
            description = "Raises in cli_app"

            def cli_app(self):
                raise RuntimeError("CLI broken")

        root_app = typer.Typer()
        plugin = BadCLIPlugin()
        # Should not raise
        register_plugin_commands(root_app, [plugin])
        assert root_app.registered_groups == []

    def test_registers_multiple_plugins(self):
        root_app = typer.Typer()

        class AnotherCLIPlugin(BasePlugin):
            name = "another"
            version = "1.0.0"
            description = "Another plugin"

            def cli_app(self):
                sub = typer.Typer(help="Another plugin.")

                @sub.command("go")
                def go():
                    pass

                return sub

        plugins = [PluginWithCLI(), AnotherCLIPlugin()]
        register_plugin_commands(root_app, plugins)
        names = [g.name for g in root_app.registered_groups]
        assert "plugin-with-cli" in names
        assert "plugin-another" in names


# ---------------------------------------------------------------------------
# get_plugin_checks
# ---------------------------------------------------------------------------


class TestGetPluginChecks:
    def test_returns_check_results(self):
        plugins = [MinimalPlugin(), PluginWithCLI()]
        results = get_plugin_checks(plugins)
        assert len(results) == 2
        assert all(isinstance(r, CheckStatus) for r in results)

    def test_catches_exception_returns_error(self):
        plugins = [BrokenCheckPlugin()]
        results = get_plugin_checks(plugins)
        assert len(results) == 1
        assert results[0].status == "error"
        assert "broken" in results[0].module

    def test_empty_plugins_list(self):
        results = get_plugin_checks([])
        assert results == []

    def test_mixed_pass_and_error(self):
        plugins = [MinimalPlugin(), BrokenCheckPlugin()]
        results = get_plugin_checks(plugins)
        statuses = {r.module: r.status for r in results}
        assert statuses["minimal"] == "pass"
        assert statuses["broken"] == "error"

    def test_base_plugin_returns_skip(self):
        plugins = [BasePlugin()]
        results = get_plugin_checks(plugins)
        assert results[0].status == "skip"


# ---------------------------------------------------------------------------
# CLI commands via CliRunner
# ---------------------------------------------------------------------------


from netglance.cli.plugin import app as plugin_app


class TestPluginListCommand:
    def test_list_empty_dir(self, tmp_path):
        result = runner.invoke(plugin_app, ["list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "No plugins found" in result.output

    def test_list_with_plugins(self, tmp_path):
        # Create a real plugin file
        plugin_file = tmp_path / "myplugin.py"
        plugin_file.write_text(
            '''\
from netglance.plugins.base import BasePlugin
from netglance.store.models import CheckStatus

class MyPlugin(BasePlugin):
    name = "myplugin"
    version = "1.2.3"
    description = "My test plugin"
'''
        )
        result = runner.invoke(plugin_app, ["list", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "myplugin" in result.output
        assert "1.2.3" in result.output

    def test_list_json_output(self, tmp_path):
        result = runner.invoke(plugin_app, ["list", "--dir", str(tmp_path), "--json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert isinstance(data, list)


class TestPluginInfoCommand:
    def test_info_not_found(self, tmp_path):
        result = runner.invoke(plugin_app, ["info", "nonexistent", "--dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_info_found(self, tmp_path):
        plugin_file = tmp_path / "infoplugin.py"
        plugin_file.write_text(
            '''\
from netglance.plugins.base import BasePlugin
from netglance.store.models import CheckStatus

class InfoPlugin(BasePlugin):
    name = "infoplugin"
    version = "3.0.0"
    description = "Info plugin for testing"
'''
        )
        result = runner.invoke(plugin_app, ["info", "infoplugin", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "infoplugin" in result.output
        assert "3.0.0" in result.output

    def test_info_json_output(self, tmp_path):
        plugin_file = tmp_path / "jsonplugin.py"
        plugin_file.write_text(
            '''\
from netglance.plugins.base import BasePlugin
from netglance.store.models import CheckStatus

class JsonPlugin(BasePlugin):
    name = "jsonplugin"
    version = "0.5.0"
    description = "JSON output plugin"
'''
        )
        result = runner.invoke(
            plugin_app, ["info", "jsonplugin", "--dir", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0
        import json

        data = json.loads(result.output, strict=False)
        assert data["name"] == "jsonplugin"
        assert data["version"] == "0.5.0"


class TestPluginDirCommand:
    def test_dir_shows_path(self):
        result = runner.invoke(plugin_app, ["dir"])
        assert result.exit_code == 0
        assert "netglance" in result.output


class TestPluginInitCommand:
    def test_init_creates_file(self, tmp_path):
        result = runner.invoke(plugin_app, ["init", "my-plugin", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        out_file = tmp_path / "my_plugin.py"
        assert out_file.exists()
        content = out_file.read_text()
        assert "my-plugin" in content
        assert "MyPlugin" in content
        assert "BasePlugin" in content

    def test_init_refuses_to_overwrite(self, tmp_path):
        out_file = tmp_path / "existing_plugin.py"
        out_file.write_text("# existing")
        result = runner.invoke(plugin_app, ["init", "existing-plugin", "--dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_init_json_output(self, tmp_path):
        result = runner.invoke(
            plugin_app, ["init", "json-init", "--dir", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0
        import json

        data = json.loads(result.output, strict=False)
        assert data["name"] == "json-init"
        assert "path" in data

    def test_init_generated_template_is_importable(self, tmp_path):
        """The generated skeleton should be a valid, importable plugin."""
        runner.invoke(plugin_app, ["init", "generated", "--dir", str(tmp_path)])
        plugin_file = tmp_path / "generated.py"
        assert plugin_file.exists()

        plugin = load_plugin(plugin_file)
        assert plugin is not None
        assert plugin.name == "generated"
        result = plugin.check()
        assert isinstance(result, CheckStatus)

    def test_init_creates_plugin_dir_if_missing(self, tmp_path):
        new_dir = tmp_path / "new" / "plugin" / "dir"
        result = runner.invoke(plugin_app, ["init", "newplugin", "--dir", str(new_dir)])
        assert result.exit_code == 0
        assert new_dir.exists()
