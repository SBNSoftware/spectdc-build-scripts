
from pathlib import Path

from modules.components import Component

class ZioTdcBuild(Component):
    name = "zio-tdc"
    installed_modules = (
        "zio.ko", "zio-buf-vmalloc.ko",
        "zio-trig-hrt.ko", "zio-trig-irq.ko", "zio-trig-timer.ko",
        "zio-ad788x.ko", "zio-fake-dtc.ko", "zio-gpio.ko",
        "zio-irq-tdc.ko", "zio-loop.ko", "zio-mini.ko",
        "zio-vmk8055.ko", "zio-zero.ko",
    )

    def build(self):
        source = Path(self.comp["source_override"])
        if not source.is_dir() and not self.runner.dry_run:
            raise FileNotFoundError(
                f"source_override path does not exist: {source}\n"
                f"Ensure fmc-tdc has been built first.")

        if self.comp.get("reset_working_tree", False):
            self.git.reset_working_tree(source)

        commit = self.comp.get("commit")
        if commit:
            self.runner.run(["git", "checkout", commit], cwd=source)

        self.patcher.apply(self.name, source)
        self.apply_exports()

        zio_subdir = source / "drivers" / "zio"
        make_dir = "drivers/zio" if zio_subdir.is_dir() else "."

        if not self.config.skip_clean:
            self.runner.make_c(make_dir, ["clean"], cwd=source)

        if not self.config.skip_build:
            self.runner.make_c(make_dir, parallel=True, cwd=source)

        if not self.config.skip_install:
            self.runner.make_c(make_dir, ["modules_install"], cwd=source,
                extra_vars={"INSTALL_MOD_PATH": str(self.config.staging_dir), "DEPMOD": "/bin/true"})

        self.mark_built()

