# behavior.py
from abc import ABC, abstractmethod
from typing import Dict, Optional, NamedTuple, List, Tuple

# --- Data Structures for Clarity ---

class VolumeArtifact(NamedTuple):
    """Represents a file that needs to be generated and mounted as a volume."""
    filename: str
    content: str
    container_path: str

class BehaviorArtifacts(NamedTuple):
    """Represents the output of a behavior generation process."""
    config_line: str
    new_volume: Optional[VolumeArtifact] = None
    section: str = 'toplevel'

# --- Abstract Base Classes ---

class Behavior(ABC):
    """
    Abstract base class for a DNS server behavior.
    Each behavior knows how to generate its own configuration artifacts.
    """
    def __init__(self, zone: str, target_name: str):
        self.zone = zone
        self.target_name = target_name

    @abstractmethod
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        """
        Generates the necessary configuration line and any associated files.
        :param service_name: The name of the service this behavior is for.
        :param target_ip: The resolved IP address of the target service.
        :return: A BehaviorArtifacts object containing the results.
        """
        pass

# --- BIND-Specific Behavior Implementations ---

class BindHintBehavior(Behavior):
    """Generates 'type hint' configuration for BIND."""
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        filename = f"gen_{service_name}_root.hints"
        # The subdir is a constant in the Builder class, we can hardcode it here
        # or pass it in the context if it needs to be more dynamic.
        container_path = f"/usr/local/etc/zones/{filename}"
        
        file_content = (
            f".\t3600000\tIN\tNS\t{self.target_name}.\n"
            f"{self.target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )
        
        config_line = f'zone "{self.zone}" {{ type hint; file "{container_path}"; }};'
        
        volume = VolumeArtifact(filename=filename, content=file_content, container_path=container_path)
        return BehaviorArtifacts(config_line=config_line, new_volume=volume)

class BindStubBehavior(Behavior):
    """Generates 'type stub' configuration for BIND."""
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        config_line = f'zone "{self.zone}" {{ type stub; masters {{ {target_ip}; }}; }};'
        return BehaviorArtifacts(config_line=config_line)

class BindForwardBehavior(Behavior):
    """Generates 'type forward' configuration for BIND."""
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        config_line = f'zone "{self.zone}" {{ type forward; forwarders {{ {target_ip}; }}; }};'
        return BehaviorArtifacts(config_line=config_line)
    
# --- Unbound-Specific Behavior Implementations ---
class UnboundHintBehavior(Behavior):
    """Generates 'root-hints' configuration for Unbound."""
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/unbound/zones/{filename}"

        file_content = (
            f".\t3600000\tIN\tNS\t{self.target_name}.\n"
            f"{self.target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )
        
        config_line = f'root-hints: "{container_path}"'
        
        volume = VolumeArtifact(filename=filename, content=file_content, container_path=container_path)
        # UPDATED: Specify that this config line belongs inside the 'server:' block.
        return BehaviorArtifacts(config_line=config_line, new_volume=volume, section='server')

class UnboundStubBehavior(Behavior):
    """Generates 'stub-zone' configuration for Unbound."""
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        config_line = f'stub-zone:\n\tname: "{self.zone}"\n\tstub-addr: {target_ip}'
        return BehaviorArtifacts(config_line=config_line)

class UnboundForwardBehavior(Behavior):
    """Generates 'forward-zone' configuration for Unbound."""
    def generate(self, service_name: str, target_ip: str) -> BehaviorArtifacts:
        config_line = f'forward-zone:\n\tname: "{self.zone}"\n\tforward-addr: {target_ip}'
        return BehaviorArtifacts(config_line=config_line)


# --- Factory ---

class BehaviorFactory:
    """
    Creates the appropriate Behavior object based on software type and behavior type.
    """
    def __init__(self):
        self._behaviors = {
            # BIND Implementations
            ("bind", "hint"): BindHintBehavior,
            ("bind", "stub"): BindStubBehavior,
            ("bind", "forward"): BindForwardBehavior,
            # To add Unbound, you would add entries here:
            ("unbound", "hint"): UnboundHintBehavior,
            ("unbound", "stub"): UnboundStubBehavior,
            ("unbound", "forward"): UnboundForwardBehavior,

            # To add more SoftWare Implementations
        }

    def _parse_behavior(self, line: str) -> Tuple[str, List[str]]:
        """
            parse a behavior
            :param line: A line from behavior config
        """
        parts = line.strip().split()
        if len(parts) == 3:
            _type = parts.pop(1);
            return (_type, parts);

    def create(self, line: str, software_type: str) -> Behavior:
        """
        Parses a behavior line and returns the correct Behavior instance.
        :param line: A line from the 'behavior' config, e.g., ". hint root-server".
        :param software_type: The software of the service, e.g., "bind".
        :return: An instance of a Behavior subclass.
        """
        behavior_type, args = self._parse_behavior(line)
        
        key = (software_type, behavior_type)
        behavior_class = self._behaviors.get(key)
        
        if not behavior_class:
            raise NotImplementedError(
                f"Behavior '{behavior_type}' is not supported for software '{software_type}'."
            )
            
        return behavior_class(*args)
    

"""
    describe the include line used for software
"""
class Includer(ABC):
    
    def __init__(self, config_line: str):
        self.config_line = config_line

    @abstractmethod
    def write(self, conf:str):
        pass


class BindIncluder(Includer):
    def write(self, conf):
        with open(conf, "a", encoding="utf-8") as _conf:
            _conf.write(f'# Auto-Include by DNS Builder\ninclude "{self.config_line}";\n')

class UnboundIncluder(Includer):
    def write(self, conf: str):
        with open(conf, "a", encoding="utf-8") as _conf:
            _conf.write(f'\n# Auto-Include by DNS Builder\ninclude: "{self.config_line}"\n')


class IncluderFactory:
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
