
from modules.components import Component

class FpgaManagerBuild(Component):
    name = "fpga-manager"
    installed_modules = ("fpga-mgr.ko",)

    def build(self):
        repo = self.clone_and_checkout()
        self.patcher.apply(self.name, repo)
        self.apply_exports()

        if not self.config.skip_clean:
            self.runner.make(["clean"], cwd=repo)

        if not self.config.skip_build:
            self.runner.make([], cwd=repo, parallel=True)

        if not self.config.skip_install:
            self.runner.make(["modules_install"], cwd=repo,
                extra_vars={"INSTALL_MOD_PATH": str(self.config.staging_dir), "DEPMOD": "/bin/true"})

        self.mark_built()

