
from modules.components import Component

class ChebyBuild(Component):
    name = "cheby"

    def build(self):
        self.clone_and_checkout()
        self.apply_exports()
        self.mark_built()

