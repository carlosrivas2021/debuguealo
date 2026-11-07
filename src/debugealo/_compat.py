"""Resolve debugealo submodule imports to their canonical debugpilot modules."""

import importlib.machinery
import sys
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader


class _CompatibilityFinder(MetaPathFinder, Loader):
    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith("debugealo."):
            return None
        legacy_name = "debugpilot." + fullname.removeprefix("debugealo.")
        module = import_module(legacy_name)
        return spec_from_loader(fullname, self, is_package=hasattr(module, "__path__"))

    def create_module(self, spec):
        legacy_name = "debugpilot." + spec.name.removeprefix("debugealo.")
        module = import_module(legacy_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):
        # The canonical implementation was loaded by create_module.
        return None


_finder = _CompatibilityFinder()


def install_compat_imports() -> None:
    if not any(isinstance(finder, _CompatibilityFinder) for finder in sys.meta_path):
        path_finder_index = sys.meta_path.index(importlib.machinery.PathFinder)
        sys.meta_path.insert(path_finder_index, _finder)
