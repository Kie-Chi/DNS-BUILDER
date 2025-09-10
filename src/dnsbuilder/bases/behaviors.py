from typing import List

from ..base import Behavior
from ..datacls.artifacts import BehaviorArtifact, VolumeArtifact
from ..exceptions import BehaviorError


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
    

