"""
DNS Builder Behavior Implementations

This module contains concrete implementations of DNS behavior classes.

Concrete classes:
- BIND behaviors: BindForwardBehavior, BindHintBehavior, BindStubBehavior, BindMasterBehavior
- Unbound behaviors: UnboundForwardBehavior, UnboundHintBehavior, UnboundStubBehavior, UnboundMasterBehavior
"""

import logging

from ..abstractions import Behavior, MasterBehavior
from ..datacls import BehaviorArtifact, VolumeArtifact, BuildContext
from ..exceptions import BehaviorError

logger = logging.getLogger(__name__)


# ============================================================================
# BIND IMPLEMENTATIONS
# ============================================================================

class BindForwardBehavior(Behavior):
    """
    Generates 'type forward' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        forwarders_list = " ".join([f"{ip};" for ip in target_ips])
        config_line = f'zone "{self.zone}" {{ type forward; forwarders {{ {forwarders_list} }}; }};'
        return BehaviorArtifact(config_line=config_line)


class BindHintBehavior(Behavior):
    """
    Generates 'type hint' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        if len(self.targets) != 1:
            raise BehaviorError(
                "The 'hint' behavior type only supports a single target."
            )

        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        target_name = self.targets[0]
        target_ip = target_ips[0]

        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/zones/{filename}"

        file_content = (
            f".\t3600000\tIN\tNS\t{target_name}.\n"
            f"{target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )

        config_line = f'zone "{self.zone}" {{ type hint; file "{container_path}"; }};'

        volume = VolumeArtifact(
            filename=filename, content=file_content, container_path=container_path
        )
        return BehaviorArtifact(config_line=config_line, new_volume=volume)


class BindStubBehavior(Behavior):
    """
    Generates 'type stub' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        masters_list = " ".join([f"{ip};" for ip in target_ips])
        config_line = (
            f'zone "{self.zone}" {{ type stub; masters {{ {masters_list} }}; }};'
        )
        return BehaviorArtifact(config_line=config_line)


class BindMasterBehavior(MasterBehavior):
    """Generates `type master` configuration for BIND"""
    
    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        return f'zone "{zone_name}" {{ type master; file "{file_path}"; }};'


# ============================================================================
# UNBOUND IMPLEMENTATIONS
# ============================================================================

class UnboundForwardBehavior(Behavior):
    """
    Generates 'forward-zone' configuration for Unbound
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        forward_addrs = "\n\t".join([f"forward-addr: {ip}" for ip in target_ips])
        config_line = f'forward-zone:\n\tname: "{self.zone}"\n\t{forward_addrs}'
        return BehaviorArtifact(config_line=config_line)


class UnboundHintBehavior(Behavior):
    """
    Generates 'root-hints' configuration for Unbound
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        if len(self.targets) != 1:
            raise BehaviorError(
                "The 'hint' behavior type only supports a single target."
            )

        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        target_name = self.targets[0]
        target_ip = target_ips[0]

        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/unbound/zones/{filename}"

        file_content = (
            f".\t3600000\tIN\tNS\t{target_name}.\n"
            f"{target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )

        config_line = f'root-hints: "{container_path}"'

        volume = VolumeArtifact(
            filename=filename,
            content=file_content,
            container_path=container_path,
            section="server",
        )
        return BehaviorArtifact(
            config_line=config_line, new_volume=volume, section="server"
        )


class UnboundStubBehavior(Behavior):
    """
    Generates 'stub-zone' configuration for Unbound
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        stub_addrs = "\n\t".join([f"stub-addr: {ip}" for ip in target_ips])
        config_line = f'stub-zone:\n\tname: "{self.zone}"\n\t{stub_addrs}'
        return BehaviorArtifact(config_line=config_line)


class UnboundMasterBehavior(MasterBehavior):
    """Generates `auth-zone` configuration for Unbound"""

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        return f'auth-zone:\n\tname: "{zone_name}"\n\tzonefile: "{file_path}"'


# ============================================================================
# PDNS RECURSOR IMPLEMENTATIONS
# ============================================================================

class PdnsRecursorForwardBehavior(Behavior):
    """
    Generates 'forward-zones' configuration for PowerDNS Recursor
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        # PowerDNS Recursor format: forward-zones=example.org=203.0.113.210, powerdns.com=2001:DB8::BEEF:5
        # Multiple IPs can be specified separated by semicolons
        forwarders = ";".join(target_ips)
        config_line = f'forward-zones+={self.zone}={forwarders}'
        return BehaviorArtifact(config_line=config_line)


class PdnsRecursorHintBehavior(Behavior):
    """
    Generates 'hint-file' configuration for PowerDNS Recursor
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        if len(self.targets) != 1:
            raise BehaviorError(
                "The 'hint' behavior type only supports a single target."
            )

        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        target_name = self.targets[0]
        target_ip = target_ips[0]

        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/zones/{filename}"

        file_content = (
            f".\t3600000\tIN\tNS\t{target_name}.\n"
            f"{target_name}.\t3600000\tIN\tA\t{target_ip}\n"
        )

        config_line = f'hint-file={container_path}'

        volume = VolumeArtifact(
            filename=filename, content=file_content, container_path=container_path
        )
        return BehaviorArtifact(config_line=config_line, new_volume=volume)


class PdnsRecursorStubBehavior(Behavior):
    """
    Generates stub configuration for PowerDNS Recursor
    
    Note: PowerDNS Recursor doesn't have a native 'stub' zone type like BIND.
    This is implemented using forward-zones with recursion disabled for compatibility.
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        # Use forward-zones for stub-like behavior
        forwarders = ";".join(target_ips)
        config_line = f'forward-zones+={self.zone}={forwarders}'
        return BehaviorArtifact(config_line=config_line)


class PdnsRecursorMasterBehavior(MasterBehavior):
    """Generates `auth-zones` configuration for PowerDNS Recursor"""

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        # PowerDNS Recursor format: auth-zones=example.org=/var/zones/example.org
        return f'auth-zones+={zone_name}={file_path}'


# Dynamically generate __all__
from ..utils.reflection import gen_exports

__all__ = gen_exports(
    ns=globals(),
    base_path='dnsbuilder.bases.behaviors',
    patterns=['Behavior']
)