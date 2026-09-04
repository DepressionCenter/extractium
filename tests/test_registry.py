"""
Summary: Tests for extractium.core.registry: registration of the three
plugin kinds, the resolution order (operator plugins/ directory, then
installed entry points, then built-ins), duplicate-name and
protocol-conformance errors, lazy loading of entry points, plugin
modules that fail to import, and the entry-point groups declared in
pyproject.toml.

This file is part of Extractium™
tests/test_registry.py

Author(s): Gabriel Mongefranco.
Created: 2026-09-04
Last Modified: 2026-09-04
Notes: See README file for documentation and full license information.
"""

# Copyright © 2026 The Regents of the University of Michigan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.

__author__ = "Gabriel Mongefranco, University of Michigan."
__copyright__ = "Copyright (C) 2026 The Regents of the University of Michigan"
__license__ = "GPLv3 or later"
__date__ = "2026-09-04"

import pathlib
import textwrap
from types import SimpleNamespace

import pytest

from extractium.core import registry

PYPROJECT_PATH = pathlib.Path(__file__).parent.parent / "pyproject.toml"

# A plugin module the tests drop into a temporary plugins/ directory. It
# registers one of each kind, all named "sample", through register().
PLUGIN_MODULE = textwrap.dedent('''
    from extractium.core.models import Extraction

    class SampleSource:
        name = "sample"
        def __init__(self, options):
            self.options = options
        def fetch(self, session, cache, progress):
            return iter(())

    class SampleHandler:
        name = "sample"
        source_type = "web"
        default_crawl_exclude_patterns = ()
        default_index_exclude_patterns = ()
        def matches(self, url):
            return False
        def fetch_url(self, url):
            return url
        def expects_html(self, url):
            return True
        def extract(self, soup, url):
            return Extraction(title="", node=soup)
        def content_type(self, url):
            return "page"

    class SampleAdapter:
        name = "sample"
        def write(self, compendium, out_dir, options):
            return ()

    def register(registry):
        registry.register_source(SampleSource)
        registry.register_site_handler(SampleHandler)
        registry.register_adapter(SampleAdapter)
''')


def make_source(name):
    """Builds a distinct, protocol-conforming source class with the given registry name."""

    class _Source:
        def __init__(self, options):
            self.options = options

        def fetch(self, session, cache, progress):
            return iter(())

    _Source.name = name
    _Source.__name__ = f"Source_{name}"
    return _Source


def make_adapter(name):
    class _Adapter:
        def write(self, compendium, out_dir, options):
            return ()

    _Adapter.name = name
    return _Adapter


class FakeEntryPoint:
    """
    Stand-in for importlib.metadata.EntryPoint: name, group, the
    distribution it came from, and load(), which returns the target or
    raises when the target cannot be imported.
    """

    def __init__(self, name, group, target, dist_name="example-plugins"):
        self.name = name
        self.group = group
        self._target = target
        self.dist = SimpleNamespace(name=dist_name)
        self.loads = 0

    def load(self):
        self.loads += 1
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


def write_plugin(plugin_dir, filename, text=PLUGIN_MODULE):
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / filename).write_text(text, encoding="utf-8")
    return plugin_dir


# ---------------------------------------------------------------------------
# Registration and lookup
# ---------------------------------------------------------------------------

def test_registered_source_is_found_by_name():
    reg = registry.Registry()
    source = make_source("web")
    reg.register_source(source)
    assert reg.get_source("web") is source


def test_each_kind_has_its_own_namespace():
    reg = registry.Registry()
    reg.register_source(make_source("shared"))
    reg.register_adapter(make_adapter("shared"))
    with pytest.raises(registry.RegistryError, match="site handler"):
        reg.get_site_handler("shared")


def test_unknown_name_lists_the_known_names():
    reg = registry.Registry()
    reg.register_source(make_source("web"))
    reg.register_source(make_source("local"))
    with pytest.raises(registry.RegistryError) as excinfo:
        reg.get_source("wbe")
    message = str(excinfo.value)
    assert "wbe" in message
    assert "local, web" in message


def test_names_lists_every_tier_once():
    reg = registry.Registry()
    reg.register_source(make_source("web"), tier=registry.Tier.BUILTIN)
    reg.register_source(make_source("web"), tier=registry.Tier.PLUGIN_DIR)
    reg.register_source(make_source("local"), tier=registry.Tier.INSTALLED)
    assert reg.source_names() == ("local", "web")


def test_duplicate_name_in_the_same_tier_is_rejected():
    reg = registry.Registry()
    reg.register_source(make_source("web"))
    with pytest.raises(registry.RegistryError, match="already registered"):
        reg.register_source(make_source("web"))


def test_class_that_does_not_satisfy_the_protocol_is_rejected():
    class NotASource:
        name = "broken"

    reg = registry.Registry()
    with pytest.raises(registry.RegistryError, match="Source protocol"):
        reg.register_source(NotASource)


def test_blank_name_is_rejected():
    reg = registry.Registry()
    with pytest.raises(registry.RegistryError, match="name"):
        reg.register_source(make_source(" "))


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------

def test_plugin_dir_shadows_a_built_in_of_the_same_name():
    reg = registry.Registry()
    builtin = make_source("web")
    dropped_in = make_source("web")
    reg.register_source(builtin, tier=registry.Tier.BUILTIN)
    reg.register_source(dropped_in, tier=registry.Tier.PLUGIN_DIR)
    assert reg.get_source("web") is dropped_in


def test_installed_package_shadows_a_built_in():
    reg = registry.Registry()
    builtin = make_source("web")
    installed = make_source("web")
    reg.register_source(builtin, tier=registry.Tier.BUILTIN)
    reg.register_source(installed, tier=registry.Tier.INSTALLED)
    assert reg.get_source("web") is installed


def test_plugin_dir_shadows_an_installed_package():
    reg = registry.Registry()
    installed = make_source("web")
    dropped_in = make_source("web")
    reg.register_source(installed, tier=registry.Tier.INSTALLED)
    reg.register_source(dropped_in, tier=registry.Tier.PLUGIN_DIR)
    assert reg.get_source("web") is dropped_in


def test_registration_order_does_not_change_precedence():
    reg = registry.Registry()
    dropped_in = make_source("web")
    reg.register_source(dropped_in, tier=registry.Tier.PLUGIN_DIR)
    reg.register_source(make_source("web"), tier=registry.Tier.BUILTIN)
    assert reg.get_source("web") is dropped_in


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def test_entry_points_from_this_package_are_built_ins():
    reg = registry.Registry()
    builtin = make_source("web")
    external = make_source("web")
    registry.load_entry_points(reg, [
        FakeEntryPoint("web", registry.ENTRY_POINT_GROUPS["sources"], builtin, dist_name="extractium"),
        FakeEntryPoint("web", registry.ENTRY_POINT_GROUPS["sources"], external),
    ])
    assert reg.get_source("web") is external


def test_entry_points_outside_the_three_groups_are_ignored():
    reg = registry.Registry()
    registry.load_entry_points(reg, [FakeEntryPoint("web", "console_scripts", make_source("web"))])
    assert reg.source_names() == ()


def test_entry_points_load_only_when_requested():
    """One broken installed package must not stop builds that never use it."""
    reg = registry.Registry()
    broken = FakeEntryPoint("broken", registry.ENTRY_POINT_GROUPS["adapters"], ImportError("no such module"))
    good = FakeEntryPoint("good", registry.ENTRY_POINT_GROUPS["adapters"], make_adapter("good"))
    registry.load_entry_points(reg, [broken, good])
    assert reg.adapter_names() == ("broken", "good")
    assert reg.get_adapter("good").name == "good"
    assert broken.loads == 0
    with pytest.raises(registry.RegistryError, match="broken"):
        reg.get_adapter("broken")


def test_entry_point_target_is_checked_against_the_protocol_when_loaded():
    reg = registry.Registry()
    registry.load_entry_points(reg, [FakeEntryPoint("bad", registry.ENTRY_POINT_GROUPS["sources"], object)])
    with pytest.raises(registry.RegistryError, match="Source protocol"):
        reg.get_source("bad")


def test_entry_point_name_must_match_the_plugin_name():
    """A mismatch would let config.yaml refer to a plugin by a name it does not answer to."""
    reg = registry.Registry()
    registry.load_entry_points(reg, [FakeEntryPoint("alias", registry.ENTRY_POINT_GROUPS["sources"], make_source("web"))])
    with pytest.raises(registry.RegistryError, match="alias"):
        reg.get_source("alias")


def test_entry_points_are_read_from_the_running_interpreter_by_default():
    """Without an explicit list, the loader consults importlib.metadata and does not fail."""
    reg = registry.Registry()
    registry.load_entry_points(reg)
    assert isinstance(reg.source_names(), tuple)


# ---------------------------------------------------------------------------
# Plugin directory
# ---------------------------------------------------------------------------

def test_plugin_module_registers_through_register(tmp_path):
    plugin_dir = write_plugin(tmp_path / "plugins", "sample_plugin.py")
    reg = registry.Registry()
    registry.load_plugin_dir(reg, plugin_dir)
    assert reg.get_source("sample").name == "sample"
    assert reg.get_site_handler("sample").name == "sample"
    assert reg.get_adapter("sample").name == "sample"


def test_plugin_dir_file_shadows_a_built_in(tmp_path):
    plugin_dir = write_plugin(tmp_path / "plugins", "sample_plugin.py")
    reg = registry.Registry()
    reg.register_source(make_source("sample"), tier=registry.Tier.BUILTIN)
    registry.load_plugin_dir(reg, plugin_dir)
    assert reg.get_source("sample").__name__ == "SampleSource"


def test_missing_plugin_dir_is_not_an_error(tmp_path):
    reg = registry.Registry()
    registry.load_plugin_dir(reg, tmp_path / "plugins")
    assert reg.source_names() == ()


def test_underscore_files_and_non_python_files_are_skipped(tmp_path):
    plugin_dir = tmp_path / "plugins"
    write_plugin(plugin_dir, "_helpers.py", "raise RuntimeError('must not be imported')\n")
    write_plugin(plugin_dir, "notes.txt", "not python\n")
    reg = registry.Registry()
    registry.load_plugin_dir(reg, plugin_dir)
    assert reg.source_names() == ()


def test_plugin_module_that_fails_to_import_names_the_file(tmp_path):
    plugin_dir = write_plugin(tmp_path / "plugins", "broken_plugin.py", "import module_that_does_not_exist\n")
    reg = registry.Registry()
    with pytest.raises(registry.RegistryError, match="broken_plugin.py"):
        registry.load_plugin_dir(reg, plugin_dir)


def test_plugin_module_without_register_names_the_file(tmp_path):
    plugin_dir = write_plugin(tmp_path / "plugins", "silent_plugin.py", "VALUE = 1\n")
    reg = registry.Registry()
    with pytest.raises(registry.RegistryError, match="silent_plugin.py.*register"):
        registry.load_plugin_dir(reg, plugin_dir)


def test_two_plugin_files_claiming_one_name_is_an_error(tmp_path):
    plugin_dir = write_plugin(tmp_path / "plugins", "first_plugin.py")
    write_plugin(plugin_dir, "second_plugin.py")
    reg = registry.Registry()
    with pytest.raises(registry.RegistryError, match="already registered"):
        registry.load_plugin_dir(reg, plugin_dir)


def test_plugin_modules_do_not_collide_with_installed_packages(tmp_path):
    """A plugin file named like a standard module must not replace that module for the process."""
    plugin_dir = write_plugin(tmp_path / "plugins", "json.py", PLUGIN_MODULE)
    reg = registry.Registry()
    registry.load_plugin_dir(reg, plugin_dir)
    import json

    assert hasattr(json, "dumps")


# ---------------------------------------------------------------------------
# Assembling the default registry
# ---------------------------------------------------------------------------

def test_build_registry_applies_the_full_order(tmp_path):
    plugin_dir = write_plugin(tmp_path / "plugins", "sample_plugin.py")
    builtin = FakeEntryPoint("sample", registry.ENTRY_POINT_GROUPS["sources"], make_source("sample"), "extractium")
    reg = registry.build_registry(plugin_dir=plugin_dir, entry_points=[builtin])
    assert reg.get_source("sample").__name__ == "SampleSource"


def test_build_registry_with_no_plugin_dir_and_no_entry_points_is_empty(tmp_path):
    reg = registry.build_registry(plugin_dir=tmp_path / "plugins", entry_points=[])
    assert reg.source_names() == ()
    assert reg.site_handler_names() == ()
    assert reg.adapter_names() == ()


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def test_pyproject_declares_the_three_entry_point_groups():
    tomllib = pytest.importorskip("tomllib")
    with open(PYPROJECT_PATH, "rb") as f:
        pyproject = tomllib.load(f)
    groups = pyproject["project"]["entry-points"]
    for group in registry.ENTRY_POINT_GROUPS.values():
        assert group in groups
