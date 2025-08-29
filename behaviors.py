# behavior.py
from abc import ABC, abstractmethod
from typing import Dict, Optional, NamedTuple

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
            # ("unbound", "stub"): UnboundStubBehavior, 
        }

    def create(self, line: str, software_type: str) -> Behavior:
        """
        Parses a behavior line and returns the correct Behavior instance.
        :param line: A line from the 'behavior' config, e.g., ". hint root-server".
        :param software_type: The software of the service, e.g., "bind".
        :return: An instance of a Behavior subclass.
        """
        parts = line.strip().split()
        if len(parts) != 3:
            raise ValueError(f"Invalid behavior line format: '{line}'")
        
        zone, behavior_type, target_name = parts
        
        key = (software_type, behavior_type)
        behavior_class = self._behaviors.get(key)
        
        if not behavior_class:
            raise NotImplementedError(
                f"Behavior '{behavior_type}' is not supported for software '{software_type}'."
            )
            
        return behavior_class(zone, target_name)