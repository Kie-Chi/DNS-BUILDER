"""
DNS Builder Behavior Implementations

This module contains concrete implementations of DNS behavior classes.

Concrete classes:
- BIND behaviors: BindForwardBehavior, BindHintBehavior, BindStubBehavior, BindMasterBehavior
- Unbound behaviors: UnboundForwardBehavior, UnboundHintBehavior, UnboundStubBehavior, UnboundMasterBehavior
"""

import logging
import ipaddress

from ..abstractions import Behavior, MasterBehavior
from ..datacls import BehaviorArtifact, VolumeArtifact, BuildContext
from ..exceptions import BehaviorError
from .. import constants

logger = logging.getLogger(__name__)


# ============================================================================
# BASE HINT BEHAVIOR
# ============================================================================

class HintBehavior(Behavior):
    """Base class for hint behaviors with common hint file generation logic"""

    # Letter sequence for generating root server names
    LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def gen_hint(self, service_name: str, build_context: BuildContext) -> str:
        """
        Generate hint file content for all targets.
        
        For service names: uses {service}.servers.net.
        For IP addresses: uses letter-based naming starting from ROOT constant
        """
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        start_letter = constants.ROOT[0].upper() if constants.ROOT else 'A'
        start_idx = self.LETTERS.index(start_letter) if start_letter in self.LETTERS else 0
        
        lines = []
        for idx, (target_name, target_ip) in enumerate(zip(self.targets, target_ips)):
            # Determine NS name based on whether target is a service or IP
            try:
                ipaddress.ip_address(target_name)
                # Pure IP address: use letter-based naming
                letter_idx = (start_idx + idx) % len(self.LETTERS)
                letter = self.LETTERS[letter_idx]
                ns_name = f"{letter}.ROOT-SERVERS.NET."
            except ValueError:
                # Service name: use service-based naming
                ns_name = f"{target_name}.servers.net."
            
            lines.append(f".\t3600000\tIN\tNS\t{ns_name}")
            lines.append(f"{ns_name}\t3600000\tIN\tA\t{target_ip}")
        
        return "\n".join(lines) + "\n"


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


class BindHintBehavior(HintBehavior):
    """
    Generates 'type hint' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/zones/{filename}"

        file_content = self.gen_hint(service_name, build_context)

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
    """
    Generates `type master` configuration for BIND.

    BIND zone configuration goes to the "zone" section with zone name as parameter.
    The Section system will format it as: zone "example.com" { ... };
    """

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """Generate the content inside the zone block."""
        return f'type master; file "{file_path}";'

    def get_section(self) -> str:
        """BIND master zones go to 'zone' section."""
        return "zone"

    def get_section_params(self, zone_name: str) -> dict:
        """Provide zone name for the zone section template."""
        return {"name": zone_name}


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


class UnboundHintBehavior(HintBehavior):
    """
    Generates 'root-hints' configuration for Unbound.

    The root-hints directive belongs to the 'server' section.
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/unbound/zones/{filename}"

        file_content = self.gen_hint(service_name, build_context)

        # root-hints directive goes in server section
        config_line = f'root-hints: "{container_path}"'

        volume = VolumeArtifact(
            filename=filename,
            content=file_content,
            container_path=container_path,
        )
        return BehaviorArtifact(
            config_line=config_line,
            section="server",
            new_volume=volume
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
        config_line = f'name: "{self.zone}"\n\t{stub_addrs}'
        
        return BehaviorArtifact(
            config_line=config_line,
            section="stub-zone"
        )


class UnboundMasterBehavior(MasterBehavior):
    """
    Generates `auth-zone` configuration for Unbound.

    Unbound authoritative zones use the "auth-zone" section.
    The Section system will format it as:
    auth-zone:
        name: "example.com"
        zonefile: "..."
    """

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """Generate auth-zone content."""
        return f'name: "{zone_name}"\n\tzonefile: "{file_path}"'

    def get_section(self) -> str:
        """Unbound master zones go to 'auth-zone' section."""
        return "auth-zone"


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


class PdnsRecursorHintBehavior(HintBehavior):
    """
    Generates 'hint-file' configuration for PowerDNS Recursor
    """

    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        filename = f"gen_{service_name}_root.hints"
        container_path = f"/usr/local/etc/zones/{filename}"

        file_content = self.gen_hint(service_name, build_context)

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
    """
    Generates `auth-zones` configuration for PowerDNS Recursor.

    PowerDNS Recursor uses simple key=value format without block structure.
    All configuration goes to the "global" section.
    """

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """Generate auth-zones configuration line."""
        # PowerDNS Recursor format: auth-zones=example.org=/var/zones/example.org
        return f'auth-zones+={zone_name}={file_path}'

    def get_section(self) -> str:
        """PowerDNS Recursor only has global section."""
        return "global"


# ============================================================================
# KNOT RESOLVER IMPLEMENTATIONS ( < 5.x )
# ============================================================================

class KnotResolverForwardBehavior(Behavior):
    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        ip_list = ", ".join([f"'{ip}'" for ip in target_ips])
        if self.zone == ".":
            config_line = f"policy.add(policy.all(policy.FORWARD({{{ip_list}}})))"
        else:
            config_line = (
                f"policy.add(policy.suffix(policy.FORWARD({{{ip_list}}}), {{todname('{self.zone}')}}))"
            )
        return BehaviorArtifact(config_line=config_line)


class KnotResolverStubBehavior(Behavior):
    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        ip_list = ", ".join([f"'{ip}'" for ip in target_ips])
        config_line = (
            f"policy.add(policy.suffix(policy.STUB({{{ip_list}}}), {{todname('{self.zone}')}}))"
        )
        return BehaviorArtifact(config_line=config_line)


class KnotResolverHintBehavior(HintBehavior):
    def generate(
        self, service_name: str, build_context: BuildContext
    ) -> BehaviorArtifact:
        target_ips = MasterBehavior.resolve_ips(self.targets, build_context, service_name)
        
        # Generate Lua table with all NS servers
        hint_entries = []
        for idx, (target_name, target_ip) in enumerate(zip(self.targets, target_ips)):
            # Determine NS name
            try:
                ipaddress.ip_address(target_name)
                letter = self.LETTERS[idx % len(self.LETTERS)]
                ns_name = f"{letter}.ROOT-SERVERS.NET."
            except ValueError:
                ns_name = f"{target_name}.servers.net."
            
            hint_entries.append(f"['{ns_name}'] = {{'{target_ip}'}}")
        
        hints_table = ", ".join(hint_entries)
        config_line = f"modules.load('hints')\nhints.root({{{hints_table}}})"

        filename = f"root.hints"
        container_path = f"/etc/knot-resolver/{filename}"
        file_content = ""
        volume = VolumeArtifact(
            filename=filename, content=file_content, container_path=container_path
        )
        return BehaviorArtifact(config_line=config_line, new_volume=volume)

# ============================================================================
# KNOT RESOLVER IMPLEMENTATIONS ( >= 6.x the same) 
# ============================================================================

class KnotResolver6HintBehavior(KnotResolverHintBehavior):
    pass

class KnotResolver6ForwardBehavior(KnotResolverForwardBehavior):
    pass

class KnotResolver6StubBehavior(KnotResolverStubBehavior):
    pass

# Dynamically generate __all__
from ..utils.reflection import gen_exports

__all__ = gen_exports(
    ns=globals(),
    base_path='dnsbuilder.bases.behaviors',
    patterns=['Behavior']
)
