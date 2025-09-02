from abc import ABC, abstractmethod


class Includer(ABC):
    """
        Abstract Class describe the `include config` line used in software config-file
    """
    def __init__(self, config_line: str):
        self.config_line = config_line

    @abstractmethod
    def write(self, conf:str):
        """
            write `include: config` line into conf

            Args:
                conf (str): main configuration file path
            
            Returns:
                None
        """
        pass

class BindIncluder(Includer):
    """
        Class describe the `include "config-file";` line for BIND
    """
    def write(self, conf):
        with open(conf, "a", encoding="utf-8") as _conf:
            _conf.write(f'# Auto-Include by DNS Builder\ninclude "{self.config_line}";\n')

class UnboundIncluder(Includer):
    """
        Class describe the `include: config-file` line for Unbound 
    """
    def write(self, conf: str):
        with open(conf, "a", encoding="utf-8") as _conf:
            _conf.write(f'\n# Auto-Include by DNS Builder\ninclude: "{self.config_line}"\n')

class IncluderFactory:
    """
        Factory Creates the appropriate Includer object based on software type
    """
    def __init__(self):
        self._includers = {
            "bind": BindIncluder,
            "unbound": UnboundIncluder,
            # other like PowerDNS etc...
        }

    def create(self, path: str, software_type: str) -> Includer:

        includer_class = self._includers.get(software_type)

        if not includer_class:
            raise NotImplementedError(
                f"Includer '{software_type}' is not supported for software '{software_type}'."
            )

        return includer_class(path)
