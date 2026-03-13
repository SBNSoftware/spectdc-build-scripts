
from modules.components import Component

class SpecCarrierBuild(Component):
    name = "spec"
    installed_modules = ("spec.ko",)
    installed_tools = ()
    cleanup_modules = ("spec",)
    cleanup_files = ("spec.ko",)

    def build(self):
        repo = self.clone_and_checkout()
        self.patcher.apply(self.name, repo)
        self.apply_exports()

        if not self.config.skip_clean:
            self.runner.make_c("kernel", ["clean"], cwd=repo)

        if not self.config.skip_build:
            self.runner.make_c("kernel", ["modules"], parallel=True, cwd=repo,
                extra_vars={"CONFIG_WR_NIC": "n"})

        if not self.config.skip_install:
            self.runner.make_c("kernel", ["modules_install"], cwd=repo,
                extra_vars={"INSTALL_MOD_PATH": str(self.config.staging_dir),
                            "CONFIG_WR_NIC": "n", "DEPMOD": "/bin/true"})

        self.mark_built()

