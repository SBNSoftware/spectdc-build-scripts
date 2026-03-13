
import logging
import platform
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

class BuildConfig:

    def __init__(self, config_path):
        self._path = Path(config_path).resolve()
        try:
            with open(self._path) as f:
                self._raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse {self._path}: {exc}") from exc

        if not isinstance(self._raw, dict):
            raise ValueError(f"Config file {self._path} must be a YAML mapping, got {type(self._raw).__name__}")

        if "build_dir" not in self._raw:
            raise ValueError("Config is missing required key 'build_dir'")

        self.build_dir = Path(self._raw["build_dir"])
        self.staging_dir = self.build_dir / "staging"
        self.kversion = self._raw.get("kversion") or platform.uname().release
        linux = self._raw.get("linux_headers")
        self.linux_headers = Path(linux) if linux else Path(f"/lib/modules/{self.kversion}/build")
        patch_dir_raw = self._raw.get("patch_dir", "../patches")
        self.patch_dir = (self._path.parent / patch_dir_raw).resolve()

        priv = self._raw.get("privilege_cmd", "sudo")
        if priv not in (None, "sudo", "ksu"):
            raise ValueError(f"privilege_cmd must be 'sudo', 'ksu', or null — got '{priv}'")
        self.privilege_cmd = priv

        skip = self._raw.get("skip", {})
        self.skip_build = bool(skip.get("build", False))
        self.skip_install = bool(skip.get("install", False))
        self.skip_patch = bool(skip.get("patch", False))
        self.skip_deps = bool(skip.get("deps", False))
        self.skip_clean = bool(skip.get("clean", False))
        if self.skip_build:
            self.skip_install = True

        log_cfg = self._raw.get("logging", {})
        self.log_level = log_cfg.get("level", "INFO")
        log_file = log_cfg.get("file")
        self.log_file = log_file if log_file else str(self.build_dir / "logs" / "build.log")
        self.log_colored = log_cfg.get("colored", True)

        self.required_executables = self._raw.get("required_executables", [])
        self.required_python_modules = self._raw.get("required_python_modules", [])

        self.marker_dir = self._path.parent / "tmp"

        self.components = self._raw.get("components", {})
        if not isinstance(self.components, dict):
            raise ValueError("Config 'components' must be a mapping")

        self._validate_components()

    def _validate_components(self):
        names = set(self.components)
        for name, comp in self.components.items():
            for dep in comp.get("depends_on", []):
                if dep not in names:
                    raise ValueError(
                        f"Component '{name}' depends on '{dep}', which is not defined in components")
            if not isinstance(comp.get("depends_on", []), list):
                raise ValueError(f"Component '{name}': depends_on must be a list")
            if not isinstance(comp.get("exports", {}), dict):
                raise ValueError(f"Component '{name}': exports must be a mapping")
            for key, val in comp.get("exports", {}).items():
                if not isinstance(val, str):
                    raise ValueError(
                        f"Component '{name}': export '{key}' value must be a string, got {type(val).__name__}")
            for flag in ("skip_patch", "reset_submodules", "reset_working_tree"):
                if flag in comp and not isinstance(comp[flag], bool):
                    raise ValueError(
                        f"Component '{name}': {flag} must be a boolean, got {type(comp[flag]).__name__}")
        if not isinstance(self.required_executables, list):
            raise ValueError("Config 'required_executables' must be a list")
        if not isinstance(self.required_python_modules, list):
            raise ValueError("Config 'required_python_modules' must be a list")

    def interpolate(self, value):
        if isinstance(value, str):
            return value.replace("{build_dir}", str(self.build_dir))
        return value

    def get_component(self, name):
        comp = self.components[name]
        result = dict(comp)
        if "exports" in result:
            result["exports"] = {
                k: self.interpolate(v) for k, v in result["exports"].items()
            }
        if "source_override" in result:
            result["source_override"] = self.interpolate(result["source_override"])
        if "path_prepend" in result:
            result["path_prepend"] = self.interpolate(result["path_prepend"])
        return result

