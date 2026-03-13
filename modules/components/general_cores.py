
from modules.components import Component

class GeneralCoresBuild(Component):
    name = "general-cores"
    installed_modules = ("htvic.ko", "i2c-ocores.ko", "spi-ocores.ko")

    def build(self):
        repo = self.clone_and_checkout()
        self.patcher.apply(self.name, repo)
        self.apply_exports()

        if not self.config.skip_clean:
            self.runner.make_c("software", ["clean"], cwd=repo)
            self.runner.make_c("software/htvic", ["clean"], cwd=repo)
            self.runner.make_c("software/i2c-ocores", ["clean"], cwd=repo)
            self.runner.make_c("software/spi-ocores", ["clean"], cwd=repo)

        if not self.config.skip_build:
            self.runner.make_c("software/htvic", parallel=True, cwd=repo)
            self.runner.make_c("software/i2c-ocores", parallel=True, cwd=repo)
            self.runner.make_c("software/spi-ocores", parallel=True, cwd=repo)

        if not self.config.skip_install:
            self.runner.make_c("software", ["install"], cwd=repo,
                extra_vars={"PREFIX": str(self.config.staging_dir)})

        self.mark_built()

