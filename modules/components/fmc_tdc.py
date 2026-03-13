
from modules.components import Component

class FmcTdcBuild(Component):
    name = "fmc-tdc"
    installed_modules = (
        "fmc-tdc.ko",
        "fmc.ko", "fmc-chardev.ko", "fmc-fakedev.ko",
        "fmc-trivial.ko", "fmc-write-eeprom.ko",
    )
    installed_tools = (
        "fmc-tdc-list", "fmc-tdc-term", "fmc-tdc-temperature",
        "fmc-tdc-time", "fmc-tdc-tstamp", "fmc-tdc-offset",
    )

    def build(self):
        repo = self.clone_and_checkout()

        if self.comp.get("reset_submodules", False):
            self.git.reset_submodules(repo)

        self.patcher.apply(self.name, repo)
        self.apply_exports()

        if not self.config.skip_clean:
            self.runner.make(["clean"], cwd=repo)

        if not self.config.skip_build:
            self.runner.make(["modules"], parallel=True, cwd=repo)
            self.runner.make_c("lib", cwd=repo)
            self.runner.make_c("tools", cwd=repo)

        if not self.config.skip_install:
            self.runner.make(["modules_install"], cwd=repo,
                extra_vars={"INSTALL_MOD_PATH": str(self.config.staging_dir), "DEPMOD": "/bin/true"})
            staging_destdir = str(self.config.staging_dir / "usr" / "local")
            self.runner.make_c("tools", ["install"], cwd=repo,
                extra_vars={"DESTDIR": staging_destdir})

        self.mark_built()

