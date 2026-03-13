
import datetime
import logging
from abc import ABC, abstractmethod
from pathlib import Path

log = logging.getLogger(__name__)

class Component(ABC):

    name: str
    installed_modules: tuple = ()
    installed_tools: tuple = ()
    cleanup_modules: tuple = ()
    cleanup_files: tuple = ()

    def __init__(self, config, build_env, runner, git, patcher):
        self.config = config
        self.build_env = build_env
        self.runner = runner
        self.git = git
        self.patcher = patcher
        self.comp = config.get_component(self.name)
        self.build_dir = config.build_dir
        self.marker = config.marker_dir / f"built.{self.name}"

    def is_built(self):
        return self.marker.is_file()

    def clone_and_checkout(self):
        return self.git.clone_and_update(
            self.comp["git_url"], self.name,
            self.comp.get("branch", "master"), self.comp.get("commit"),
        )

    def apply_exports(self):
        for key, value in self.comp.get("exports", {}).items():
            self.build_env.export(key, value)
        if "path_prepend" in self.comp:
            self.build_env.prepend_path(self.comp["path_prepend"])

    def mark_built(self):
        if not self.runner.dry_run:
            self.marker.touch()

        if not self.config.skip_install:
            staging = self.config.staging_dir
            staged_extra = staging / "lib" / "modules" / self.config.kversion / "extra"
            if staged_extra.is_dir():
                log.info("  Staged kernel modules in %s:", staged_extra)
                try:
                    for ko in sorted(staged_extra.rglob("*.ko")):
                        log.info("    %s (%d bytes)", ko.name, ko.stat().st_size)
                except OSError:
                    pass

            staged_tools = staging / "usr" / "local" / "bin"
            if staged_tools.is_dir():
                log.info("  Staged tools in %s:", staged_tools)
                try:
                    for f in sorted(staged_tools.iterdir()):
                        if f.is_file():
                            log.info("    %s", f.name)
                except OSError:
                    pass

        summary_log = self.build_dir / "logs" / "build_summary.log"
        if summary_log.parent.is_dir() and not self.runner.dry_run:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(summary_log, "a") as f:
                f.write(f"{ts} {self.name} completed\n")

        log.info("  %s build complete", self.name)

    def uninstall(self):
        kversion = self.config.kversion
        extra_dir = Path(f"/lib/modules/{kversion}/extra")
        tools_dir = Path("/usr/local/bin")
        for ko in self.installed_modules:
            self.runner.privileged_run(
                ["/usr/bin/find", str(extra_dir), "-name", ko, "-delete"],
                check=False)
        for ko in self.cleanup_files:
            self.runner.privileged_run(
                ["/usr/bin/find", str(extra_dir), "-name", ko, "-delete"],
                check=False)
        for tool in self.installed_tools:
            self.runner.privileged_run(
                ["/usr/bin/rm", "-f", str(tools_dir / tool)], check=False)

    @abstractmethod
    def build(self):
        pass

from modules.components.cheby import ChebyBuild
from modules.components.wbgen2 import Wbgen2Build
from modules.components.fpga_manager import FpgaManagerBuild
from modules.components.general_cores import GeneralCoresBuild
from modules.components.spec import SpecCarrierBuild
from modules.components.fmc_tdc import FmcTdcBuild
from modules.components.zio_tdc import ZioTdcBuild

COMPONENT_CLASSES = {
    "cheby":          ChebyBuild,
    "wishbone-gen":   Wbgen2Build,
    "fpga-manager":   FpgaManagerBuild,
    "general-cores":  GeneralCoresBuild,
    "spec":           SpecCarrierBuild,
    "fmc-tdc":        FmcTdcBuild,
    "zio-tdc":        ZioTdcBuild,
}

