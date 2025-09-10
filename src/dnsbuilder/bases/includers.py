from ..base import Includer


# -------------------------
#
#   BIND IMPLEMENTATIONS
#
# -------------------------

class BindIncluder(Includer):
    """
        Class describe the `include "config-file";` line for BIND
    """
    def write(self, conf):
        with open(conf, "a", encoding="utf-8") as _conf:
            _conf.write(f'# Auto-Include by DNS Builder\ninclude "{self.config_line}";\n')

# -------------------------
#
#   UNBOUND IMPLEMENTATIONS
#
# -------------------------

class UnboundIncluder(Includer):
    """
        Class describe the `include: config-file` line for Unbound 
    """
    def write(self, conf: str):
        with open(conf, "a", encoding="utf-8") as _conf:
            _conf.write(f'\n# Auto-Include by DNS Builder\ninclude: "{self.config_line}"\n')

