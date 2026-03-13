
import importlib.util
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

class BuildEnvironment:

    def __init__(self, config):
        self.config = config
        self.env = os.environ.copy()
        self.env["BUILD_DIR"] = str(config.build_dir)
        self.env["KVERSION"] = config.kversion
        self.env["LINUX"] = str(config.linux_headers)
        self.env["KERNELSRC"] = str(config.linux_headers)

    def export(self, key, value):
        self.env[key] = value
        log.debug("export %s=%s", key, value)

    def prepend_path(self, directory):
        current = self.env.get("PATH", "")
        self.env["PATH"] = f"{directory}:{current}"
        log.debug("PATH prepend: %s", directory)

    def privilege_prefix(self):
        priv = self.config.privilege_cmd
        if priv == "sudo":
            return ["sudo", "-E"]
        elif priv == "ksu":
            return ["ksu", "-q", "-e"]
        return []

    def get(self):
        return self.env

class CommandRunner:

    def __init__(self, build_env, dry_run=False):
        self.build_env = build_env
        self.dry_run = dry_run

    def run(self, cmd, cwd=None, check=True):
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else cmd
        log.info("  >> %s", cmd_str)
        if cwd:
            log.debug("     cwd=%s", cwd)

        if self.dry_run:
            log.info("  [dry-run] skipped")
            return subprocess.CompletedProcess(cmd if isinstance(cmd, list) else [cmd], returncode=0)

        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=self.build_env.get(),
            shell=isinstance(cmd, str),
            check=check,
            stdout=None,
            stderr=None,
        )
        return result

    def make(self, targets, cwd, parallel=False, extra_vars=None):
        cmd = ["make"]
        if parallel:
            cmd += [f"-j{os.cpu_count()}"]
        if extra_vars:
            cmd += [f"{k}={v}" for k, v in extra_vars.items()]
        cmd += list(targets)
        self.run(cmd, cwd=cwd)

    def make_c(self, subdir, targets=None, parallel=False, extra_vars=None, cwd=None):
        cmd = ["make"]
        if parallel:
            cmd += [f"-j{os.cpu_count()}"]
        cmd += ["-C", str(subdir)]
        if extra_vars:
            cmd += [f"{k}={v}" for k, v in extra_vars.items()]
        if targets:
            cmd += list(targets)
        self.run(cmd, cwd=cwd)

    def privileged_run(self, cmd_args, cwd=None, check=True):
        cmd_args = list(cmd_args)
        if cmd_args and not str(cmd_args[0]).startswith("/"):
            raise ValueError(f"privileged_run requires absolute path, got: {cmd_args[0]}")
        cmd = self.build_env.privilege_prefix() + cmd_args
        return self.run(cmd, cwd=cwd, check=check)

class DependencyChecker:

    def __init__(self, config):
        self.config = config
        self.deps_ok = config.marker_dir / "deps.ok"

    def _check_passwordless_privilege(self, priv):
        try:
            if priv == "sudo":
                result = subprocess.run(
                    ["sudo", "-n", "true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            elif priv == "ksu":
                result = subprocess.run(
                    ["ksu", "-q", "-e", "/bin/true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            else:
                return True

            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, priv)

        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
            log.error(
                'Passwordless %s access is not available for user "%s". '
                'Configure passwordless %s, set privilege_cmd to an alternative '
                'in config.yaml, or set skip.install to true.',
                priv, os.environ.get("USER", "unknown"), priv,
            )
            return False
        return True

    def check_all(self):
        if self.deps_ok.is_file():
            log.info("Dependencies already verified (deps.ok exists)")
            return

        fail = False

        for exe in self.config.required_executables:
            if exe in ("sudo", "ksu"):
                if self.config.skip_install or exe != self.config.privilege_cmd:
                    continue
            if not shutil.which(exe):
                log.error('"%s" not found in system path. Please install it.', exe)
                fail = True

        if not self.config.skip_install and self.config.privilege_cmd:
            priv = self.config.privilege_cmd
            if not shutil.which(priv):
                log.error('Privilege command "%s" not found in system path. '
                          'Please install it or set privilege_cmd to null in config.yaml.', priv)
                fail = True
            elif not self._check_passwordless_privilege(priv):
                fail = True

        for mod in self.config.required_python_modules:
            if importlib.util.find_spec(mod) is None:
                log.error('Python module "%s" not found. Please install it.', mod)
                fail = True

        if not self.config.linux_headers.exists():
            log.error("Missing kernel headers at %s", self.config.linux_headers)
            fail = True

        if fail:
            log.critical("Dependency check failed — aborting")
            sys.exit(1)

        self.deps_ok.touch()
        log.info("All dependencies satisfied")

