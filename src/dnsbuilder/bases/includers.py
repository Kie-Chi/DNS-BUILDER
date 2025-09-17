from ..base import Includer
from ..io.path import DNSBPath

# -------------------------
#
#   BIND IMPLEMENTATIONS
#
# -------------------------

class BindIncluder(Includer):
    """
        Class describe the `include "config-file";` line for BIND
    """
    def write(self, conf: DNSBPath):
        content = f'\n# Auto-Include by DNS Builder\ninclude "{self.config_line}";\n'
        self.fs.append_text(conf, content)

# -------------------------
#
#   UNBOUND IMPLEMENTATIONS
#
# -------------------------

class UnboundIncluder(Includer):
    """
        Class describe the `include: config-file` line for Unbound 
    """
    def write(self, conf: DNSBPath):
        content = f'\n# Auto-Include by DNS Builder\ninclude: "{self.config_line}"\n'
        self.fs.append_text(conf, content)

