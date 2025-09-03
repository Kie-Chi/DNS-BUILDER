from abc import ABC, abstractmethod
from typing import List, Tuple, Any
from .artifacts import BehaviorArtifact, VolumeArtifact
from ..exceptions import BehaviorError

# BASE CLASS
class Behavior(ABC):
    """
        Abstract Class for a DNS server behavior
        Each behavior can generate its own configuration artifact
    """
    def __init__(self, zone: str, targets: List[str]):
        self.zone = zone
        self.targets = targets

    @abstractmethod
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        """
        Generates the necessary configuration line and any associated files.
        :param service_name: The name of the service this behavior is for.
        :param target_ips: The resolved IP addresses of the target services.
        :return: A BehaviorArtifact object containing the results.
        """
        pass

# -------------------------
# 
#   BIND IMPLEMENTATIONS
# 
# -------------------------

class BindForwardBehavior(Behavior):
    """
        Class represents behavior of Generating 'type forward' configuration for BIND
    """
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        forwarders_list = " ".join([f"{ip};" for ip in target_ips])
        config_line = f'zone "{self.zone}" {{ type forward; forwarders {{ {forwarders_list} }}; }};'
        return BehaviorArtifact(config_line=config_line)
    

class BindHintBehavior(Behavior):
    """
        Class represents behavior of Generating 'type hint' configuration for BIND
    """
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        if len(self.targets) != 1 or len(target_ips) != 1:
            raise BehaviorError("The 'hint' behavior type only supports a single target.")
        target_name = self.targets[0]
        target_ip = target_ips[0]

        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/zones/{filename}"
        
        file_content = (
            f".\t3600000\tIN\tNS\t{target_name}.\n"
            f"{target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )
        
        config_line = f'zone "{self.zone}" {{ type hint; file "{container_path}"; }};'
        
        volume = VolumeArtifact(filename=filename, content=file_content, container_path=container_path)
        return BehaviorArtifact(config_line=config_line, new_volume=volume)
    

class BindStubBehavior(Behavior):
    """
        Class represents behavior of Generating 'type stub' configuration for BIND
    """
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        masters_list = " ".join([f"{ip};" for ip in target_ips])
        config_line = f'zone "{self.zone}" {{ type stub; masters {{ {masters_list} }}; }};'
        return BehaviorArtifact(config_line=config_line)
    

# -------------------------
# 
#   Unbound IMPLEMENTATIONS
# 
# -------------------------

class UnboundForwardBehavior(Behavior):
    """
        Class represents behavior of Generating 'forward-zone' configuration for Unbound
    """
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        forward_addrs = '\n\t'.join([f'forward-addr: {ip}' for ip in target_ips])
        config_line = f'forward-zone:\n\tname: "{self.zone}"\n\t{forward_addrs}'
        return BehaviorArtifact(config_line=config_line)
    

class UnboundHintBehavior(Behavior):
    """
        Class represents behavior of Generating 'root-hints' configuration for Unbound
    """
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        if len(self.targets) != 1 or len(target_ips) != 1:
            raise BehaviorError("The 'hint' behavior type only supports a single target.")
        target_name = self.targets[0]
        target_ip = target_ips[0]

        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/unbound/zones/{filename}"

        file_content = (
            f".\t3600000\tIN\tNS\t{target_name}.\n"
            f"{target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )
        
        config_line = f'root-hints: "{container_path}"'
        
        volume = VolumeArtifact(filename=filename, content=file_content, container_path=container_path)
        return BehaviorArtifact(config_line=config_line, new_volume=volume, section='server')


class UnboundStubBehavior(Behavior):
    """
        Class represents behavior of Generating 'stub-zone' configuration for Unbound
    """
    def generate(self, service_name: str, target_ips: List[str]) -> BehaviorArtifact:
        stub_addrs = '\n\t'.join([f'stub-addr: {ip}' for ip in target_ips])
        config_line = f'stub-zone:\n\tname: "{self.zone}"\n\t{stub_addrs}'
        return BehaviorArtifact(config_line=config_line)
    

# -------------------------
# 
#   BEHAVIOR FACTORY
# 
# -------------------------

class BehaviorFactory:
    def __init__(self):
        self._behaviors = {
            # BIND Implementations
            ("bind", "hint"): BindHintBehavior,
            ("bind", "stub"): BindStubBehavior,
            ("bind", "forward"): BindForwardBehavior,
            # Unbound Implementations
            ("unbound", "hint"): UnboundHintBehavior,
            ("unbound", "stub"): UnboundStubBehavior,
            ("unbound", "forward"): UnboundForwardBehavior,
            # To add more SoftWare Implementations
        }

    def _parse_behavior(self, line: str) -> Tuple[str, List[Any]]:
        """
            parse a behavior
            Args:
                line (str): A line from behavior config
            
            Returns:
                Tuple[str, List[Any]]
                behavior_type, args used for init behavior (zone, targets)
        """
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3:
            raise ValueError(f"Invalid behavior format: '{line}'. Expected '<zone> <type> <target1>,<target2>...'.")

        zone, behavior_type, targets_str = parts
        targets = [t.strip() for t in targets_str.split(',')]
        
        return (behavior_type, [zone, targets])

    def create(self, line: str, software_type: str) -> Behavior:
        """
            Parses a behavior line and returns the correct Behavior instance
            Args:
                line (str): A line from the 'behavior' config, e.g., ". forward root-server,8.8.8.8"
                software_type (str): The software of the service, e.g., "bind"
            
            Returns:
                behavior(Behavior): An instance of a Behavior subclass
        """
        behavior_type, args = self._parse_behavior(line)
        
        key = (software_type, behavior_type)
        behavior_class = self._behaviors.get(key)
        
        if not behavior_class:
            raise NotImplementedError(
                f"Behavior '{behavior_type}' is not supported for software '{software_type}'."
            )
            
        return behavior_class(*args)