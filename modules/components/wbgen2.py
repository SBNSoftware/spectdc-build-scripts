
from modules.components import Component

class Wbgen2Build(Component):
    name = "wishbone-gen"

    def build(self):
        self.clone_and_checkout()
        self.apply_exports()
        self.mark_built()

