"""
Summary: The plugin registry that resolves the three plugin kinds an
Extractium build uses: sources (produce documents), site handlers
(extract content from web pages the crawler visits), and adapters (write
output formats). Resolution order, first match wins: the operator's
local plugins/ directory, then entry points from installed packages,
then the built-ins that ship with this package, which are declared
through the same entry-point groups. See docs/extractium-spec.md
section 2.

This file is part of Extractium™
extractium/core/registry.py

Author(s): Gabriel Mongefranco.
Created: 2026-08-17
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

import enum
import importlib.metadata
import importlib.util
import pathlib
import sys

from extractium.core.models import Adapter, SiteHandler, Source

### Constants ###

# Entry-point group per plugin kind. A package that installs a plugin
# declares it under one of these groups; the built-ins that ship with
# Extractium are declared the same way in this project's pyproject.toml.
ENTRY_POINT_GROUPS = {
    "sources": "extractium.sources",
    "site_handlers": "extractium.site_handlers",
    "adapters": "extractium.adapters",
}

# Entry points from this distribution are the built-in tier; entry points
# from any other distribution are the installed tier and shadow them.
BUILTIN_DISTRIBUTION = "extractium"

# The protocol each kind must satisfy and the label error messages use.
_KINDS = {
    "sources": (Source, "source"),
    "site_handlers": (SiteHandler, "site handler"),
    "adapters": (Adapter, "adapter"),
}

# Folder the operator drops plugin modules into, relative to the working
# directory the build runs from.
DEFAULT_PLUGIN_DIR = "plugins"

# Namespace plugin modules are imported under, so a plugin file called
# json.py never replaces the standard library's json for the process.
_PLUGIN_MODULE_PREFIX = "extractium_plugins."


class Tier(enum.IntEnum):
    """
    Where a plugin came from. Lower values win when two tiers register
    the same name, so an operator's plugins/ folder overrides an
    installed package, which overrides a built-in.
    """

    PLUGIN_DIR = 0
    INSTALLED = 1
    BUILTIN = 2


class RegistryError(Exception):
    """
    Raised when a plugin cannot be registered or found: a name that is
    unknown, blank, or already taken in its tier; a class that does not
    satisfy its kind's protocol; or a plugin module that cannot be
    imported. The message names the plugin, the file, or the entry
    point, and is safe to show a user.
    """


### Lazy Entry-Point Loading ###

class _LazyPlugin:
    """
    An entry point that is loaded on first use, so one installed package
    that fails to import cannot stop a build that never asked for it.
    """

    def __init__(self, entry_point):
        self.entry_point = entry_point
        self.loaded = None

    def load(self):
        if self.loaded is None:
            try:
                self.loaded = self.entry_point.load()
            except Exception as e:
                raise RegistryError(
                    f"entry point {self.entry_point.name!r} in group "
                    f"{self.entry_point.group!r} cannot be loaded ({e})."
                ) from e
        return self.loaded


### Registry ###

class Registry:
    """
    Name-to-class maps for the three plugin kinds, each split by tier.

    A plugin is registered under its own `name` attribute. Lookups walk
    the tiers in precedence order and return the first class that
    answers to the name. Registering a plugin whose class does not
    satisfy its kind's protocol fails at once, so a mistake surfaces
    when the plugin is loaded rather than mid-build.
    """

    def __init__(self):
        self._entries = {
            kind: {tier: {} for tier in Tier} for kind in _KINDS
        }

    ### Registration ###

    def _register(self, kind, plugin, tier):
        """
        Stores plugin under its name in the given tier of kind.

        Args:
            kind (str): "sources", "site_handlers", or "adapters".
            plugin (type | _LazyPlugin): the plugin class, or a lazy
                entry point whose name is checked when it is loaded.
            tier (Tier): which tier the plugin belongs to.

        Raises:
            RegistryError: if the name is blank, already registered in
                that tier, or the class fails the protocol check.
        """
        tier = Tier(tier)
        if isinstance(plugin, _LazyPlugin):
            name = plugin.entry_point.name
        else:
            self._check_conforms(kind, plugin)
            name = plugin.name
        if not isinstance(name, str) or not name.strip():
            raise RegistryError(f"a {_KINDS[kind][1]} plugin must have a non-blank name; got {name!r}.")
        registered = self._entries[kind][tier]
        if name in registered:
            raise RegistryError(
                f"{_KINDS[kind][1]} {name!r} is already registered in the {tier.name.lower()} tier."
            )
        registered[name] = plugin

    def _check_conforms(self, kind, plugin):
        """Raises RegistryError unless plugin satisfies the kind's protocol."""
        protocol, label = _KINDS[kind]
        if not isinstance(plugin, protocol):
            raise RegistryError(
                f"{getattr(plugin, '__name__', repr(plugin))} does not satisfy the "
                f"{protocol.__name__} protocol required of a {label}."
            )

    def register_source(self, plugin, tier=Tier.PLUGIN_DIR):
        """Registers a Source class. Plugin modules call this from register()."""
        self._register("sources", plugin, tier)

    def register_site_handler(self, plugin, tier=Tier.PLUGIN_DIR):
        """Registers a SiteHandler class. Plugin modules call this from register()."""
        self._register("site_handlers", plugin, tier)

    def register_adapter(self, plugin, tier=Tier.PLUGIN_DIR):
        """Registers an Adapter class. Plugin modules call this from register()."""
        self._register("adapters", plugin, tier)

    ### Lookup ###

    def _get(self, kind, name):
        """
        Returns the highest-precedence class registered under name.

        Raises:
            RegistryError: if no tier knows the name, or the entry point
                that claims it cannot be loaded, answers to a different
                name, or fails the protocol check.
        """
        label = _KINDS[kind][1]
        for tier in Tier:
            plugin = self._entries[kind][tier].get(name)
            if plugin is None:
                continue
            if isinstance(plugin, _LazyPlugin):
                plugin = self._resolve_lazy(kind, name, plugin)
            return plugin
        known = ", ".join(self._names(kind)) or "none"
        raise RegistryError(f"no {label} named {name!r}. Known {label}s: {known}.")

    def _resolve_lazy(self, kind, name, lazy):
        """Loads an entry point and checks it answers to the registered name."""
        plugin = lazy.load()
        self._check_conforms(kind, plugin)
        if plugin.name != name:
            raise RegistryError(
                f"entry point {name!r} loads a {_KINDS[kind][1]} whose name is "
                f"{plugin.name!r}; the two must match."
            )
        return plugin

    def get_source(self, name):
        """Returns the Source class registered under name."""
        return self._get("sources", name)

    def get_site_handler(self, name):
        """Returns the SiteHandler class registered under name."""
        return self._get("site_handlers", name)

    def get_adapter(self, name):
        """Returns the Adapter class registered under name."""
        return self._get("adapters", name)

    ### Listing ###

    def _names(self, kind):
        """Sorted names known to any tier of kind, each once. Loads nothing."""
        names = set()
        for tier in Tier:
            names.update(self._entries[kind][tier])
        return tuple(sorted(names))

    def source_names(self):
        """Sorted names of every registered source."""
        return self._names("sources")

    def site_handler_names(self):
        """Sorted names of every registered site handler."""
        return self._names("site_handlers")

    def adapter_names(self):
        """Sorted names of every registered adapter."""
        return self._names("adapters")


### Load Entry Points ###

def _is_builtin(entry_point):
    """True when the entry point belongs to this package's own distribution."""
    dist = getattr(entry_point, "dist", None)
    dist_name = getattr(dist, "name", None) or ""
    return dist_name.lower() == BUILTIN_DISTRIBUTION


def _installed_entry_points():
    """Every entry point in the three groups, from the running interpreter's installed packages."""
    found = []
    for group in ENTRY_POINT_GROUPS.values():
        found.extend(importlib.metadata.entry_points(group=group))
    return found


def load_entry_points(registry, entry_points=None):
    """
    Registers entry points, lazily, into the installed or built-in tier.

    Args:
        registry (Registry): the registry to fill.
        entry_points (Iterable | None): entry-point objects exposing name,
            group, dist, and load(). None reads the running interpreter's
            installed packages.

    Side effects:
        None at load time; each entry point is imported on first lookup.

    Raises:
        RegistryError: if two entry points in one tier claim one name.
    """
    if entry_points is None:
        entry_points = _installed_entry_points()
    group_to_kind = {group: kind for kind, group in ENTRY_POINT_GROUPS.items()}
    for entry_point in entry_points:
        kind = group_to_kind.get(entry_point.group)
        if kind is None:
            continue
        tier = Tier.BUILTIN if _is_builtin(entry_point) else Tier.INSTALLED
        registry._register(kind, _LazyPlugin(entry_point), tier)


### Load Plugin Directory ###

def load_plugin_dir(registry, plugin_dir=DEFAULT_PLUGIN_DIR):
    """
    Imports every plugin module in a directory and lets each register.

    Each `*.py` file whose name does not start with an underscore is
    imported and its `register(registry)` function is called. Files are
    processed in name order. A missing directory registers nothing.

    Importing a module runs the code the operator placed in that folder,
    at the same trust level as the configuration file. This is
    documented, not sandboxed.

    Args:
        registry (Registry): the registry to fill.
        plugin_dir (str | pathlib.Path): the folder to scan.

    Raises:
        RegistryError: if a module cannot be imported, has no register()
            function, or registers a name already taken in this tier.
    """
    plugin_dir = pathlib.Path(plugin_dir)
    if not plugin_dir.is_dir():
        return
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = _import_plugin_module(path)
        register = getattr(module, "register", None)
        if not callable(register):
            raise RegistryError(f"{path}: plugin module has no register(registry) function.")
        try:
            register(registry)
        except RegistryError:
            raise
        except Exception as e:
            raise RegistryError(f"{path}: register() failed ({e}).") from e


def _import_plugin_module(path):
    """Imports one plugin file under the plugin namespace and returns the module."""
    module_name = _PLUGIN_MODULE_PREFIX + path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    # Registered under its namespaced name so dataclasses and pickling
    # inside the plugin can find their own module.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(module_name, None)
        raise RegistryError(f"{path}: plugin module cannot be imported ({e}).") from e
    return module


### Build Registry ###

def build_registry(plugin_dir=DEFAULT_PLUGIN_DIR, entry_points=None):
    """
    Assembles the registry a build uses, in resolution order.

    Args:
        plugin_dir (str | pathlib.Path): the operator's plugin folder.
        entry_points (Iterable | None): entry points to register; None
            reads the installed packages.

    Returns:
        Registry: plugins/ modules in the top tier, installed packages
        next, this package's built-ins last.

    Raises:
        RegistryError: for any registration failure described above.
    """
    registry = Registry()
    load_plugin_dir(registry, plugin_dir)
    load_entry_points(registry, entry_points)
    return registry
