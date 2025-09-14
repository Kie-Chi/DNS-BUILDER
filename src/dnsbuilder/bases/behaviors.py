from typing import List, Tuple, TYPE_CHECKING
from abc import ABC, abstractmethod
from ..base import Behavior
if TYPE_CHECKING:
    from ..datacls.contexts import BuildContext
from dnslib import RR, NS, CNAME, A, QTYPE
import ipaddress
from .. import constants
from ..datacls.artifacts import BehaviorArtifact, VolumeArtifact
from ..exceptions import BehaviorError, UnsupportedFeatureError

import logging

logger = logging.getLogger(__name__)

# -------------------------
#
#   HELPER IMPLEMENTATIONS
#
# -------------------------

def _resolve_target_ips(
    targets: List[str], build_context: "BuildContext", service_name: str, ignore: bool = False
) -> List[str]:
    """Resolves a list of behavior targets, which can be service names or IPs."""
    resolved_ips = []
    for target in targets:
        try:
            ipaddress.ip_address(target)
            resolved_ips.append(target)
            continue
        except ValueError:
            pass  # Not an IP, assume it's a service name

        target_ip = build_context.service_ips.get(target)
        if not target_ip:
            if ignore:
                continue
            raise BehaviorError(
                f"Behavior in '{service_name}' references an undefined service or invalid IP: '{target}'."
            )
        resolved_ips.append(target_ip)
    return resolved_ips


# -------------------------
#
#   ALL IMPLEMENTATIONS
#
# -------------------------

class MasterBehavior(Behavior, ABC):
    """Base class for master behaviors to share parsing logic."""

    def __init__(self, zone: str, args_str: str):
        # zone is the target zone file name, e.g. "com" for "db.com"
        # args_str is the record, e.g. "example.com A 1.2.3.4"
        self.zone_file_key = zone
        rname, self.record_type, targets_str, self.ttl = self._parse_args(args_str)
        # Use rname as the 'zone' for the base Behavior class, which it uses as rname
        super().__init__(rname, [t.strip() for t in targets_str.split(",")])

    def _parse_args(self, args_str: str) -> Tuple[str]:
        """Parse record args from origin string"""
        # Expected format: "<rname> <type> <ttl> <target1>,<target2>..."
        parts = args_str.strip().split(maxsplit=3)
        ttl = 3600
        if len(parts) == 4:
            try:
                ttl = int(parts[2])
            except Exception:
                logger.warning(
                    f"Invalid TTL value '{parts[2]}' for record '{parts[0]}' in zone '{self.zone_file_key}'. "
                    f"Using default TTL."
                )
                pass
        elif len(parts) == 3:
            pass
        elif len(parts) != 3:
            raise UnsupportedFeatureError(
                f"Invalid 'master' behavior format for zone '{self.zone_file_key}'. "
                f"Expected '<record-name> <type> [<ttl>] <target1>,<target2>...', got '{args_str}'."
            )
        # rname, rtype, targets_str
        return parts[0], parts[1].upper(), parts[-1], ttl

    @abstractmethod
    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """Generate config line for this behavior due to software"""
        pass

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        """Generate behavior artifact for this behavior, handling different record types."""
        records = []
        try:
            rtype_id = getattr(QTYPE, self.record_type)
        except AttributeError:
            raise UnsupportedFeatureError(
                f"Unsupported record type '{self.record_type}'."
            )

        if self.zone == '@':
            rname = self.zone_file_key
        elif not self.zone.endswith('.'):
            if self.zone_file_key == ".":
                rname = f"{self.zone}."
            else:
                rname = f"{self.zone}.{self.zone_file_key}"
        else:
            rname = self.zone

        if self.record_type in ("A", "AAAA"):
            target_ips = _resolve_target_ips(self.targets, build_context, service_name)
            record_class = constants.RECORD_TYPE_MAP.get(self.record_type)
            if not record_class:
                raise UnsupportedFeatureError(
                    f"Unsupported record type '{self.record_type}'."
                )  # Should not happen
            records.extend(
                [
                    RR(rname=rname, rtype=rtype_id, rdata=record_class(ip), ttl=self.ttl)
                    for ip in target_ips
                ]
            )

        elif self.record_type == "NS":
            _iter = 0
            for target in self.targets:
                # Check for and generate glue records
                target_ip = build_context.service_ips.get(target)
                if target_ip:
                    ns_name = f"ns{_iter}.{rname}"
                    records.append(
                        RR(
                            rname=rname,
                            rtype=rtype_id,
                            rdata=NS(ns_name),
                            ttl=self.ttl,
                        )
                    )
                    records.append(
                        RR(
                            rname=ns_name,
                            rtype=QTYPE.A,
                            rdata=A(target_ip),
                            ttl=self.ttl
                        )
                    )
                    _iter += 1
                else:
                    # External
                    records.append(
                        RR(rname=rname, rtype=rtype_id, rdata=NS(target), ttl=self.ttl)
                    )

        elif self.record_type == "CNAME":
            for target_domain in self.targets:
                records.append(
                    RR(rname=rname, rtype=rtype_id, rdata=CNAME(target_domain), ttl=self.ttl)
                )

        else:
            # For other types like TXT, treat targets as string data
            record_class = constants.RECORD_TYPE_MAP.get(self.record_type)
            if not record_class:
                raise UnsupportedFeatureError(
                    f"Unsupported record type '{self.record_type}' in master behavior for zone '{rname}'."
                )
            # TXT rdata needs to be a list of strings/bytes
            rdata_val = [t.encode("utf-8") for t in self.targets]
            records.append(
                RR(
                    rname=rname,
                    rtype=rtype_id,
                    rdata=record_class(rdata_val),
                    ttl=self.ttl,
                )
            )

        return BehaviorArtifact(config_line="", new_records=records)


# -------------------------
# 
#   BIND IMPLEMENTATIONS
# 
# -------------------------

class BindForwardBehavior(Behavior):
    """
    Class represents behavior of Generating 'type forward' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        target_ips = _resolve_target_ips(self.targets, build_context, service_name)
        forwarders_list = " ".join([f"{ip};" for ip in target_ips])
        config_line = f'zone "{self.zone}" {{ type forward; forwarders {{ {forwarders_list} }}; }};'
        return BehaviorArtifact(config_line=config_line)


class BindHintBehavior(Behavior):
    """
    Class represents behavior of Generating 'type hint' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        if len(self.targets) != 1:
            raise BehaviorError(
                "The 'hint' behavior type only supports a single target."
            )

        target_ips = _resolve_target_ips(self.targets, build_context, service_name)
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
    Class represents behavior of Generating 'type stub' configuration for BIND
    """

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        target_ips = _resolve_target_ips(self.targets, build_context, service_name)
        masters_list = " ".join([f"{ip};" for ip in target_ips])
        config_line = (
            f'zone "{self.zone}" {{ type stub; masters {{ {masters_list} }}; }};'
        )
        return BehaviorArtifact(config_line=config_line)


class BindMasterBehavior(MasterBehavior):
    """Generates `type master` configuration for BIND."""
    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        return f'zone "{zone_name}" {{ type master; file "{file_path}"; }};'


# -------------------------
# 
#   Unbound IMPLEMENTATIONS
# 
# -------------------------

class UnboundForwardBehavior(Behavior):
    """
    Class represents behavior of Generating 'forward-zone' configuration for Unbound
    """

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        target_ips = _resolve_target_ips(self.targets, build_context, service_name)
        forward_addrs = "\n\t".join([f"forward-addr: {ip}" for ip in target_ips])
        config_line = f'forward-zone:\n\tname: "{self.zone}"\n\t{forward_addrs}'
        return BehaviorArtifact(config_line=config_line)


class UnboundHintBehavior(Behavior):
    """
    Class represents behavior of Generating 'root-hints' configuration for Unbound
    """

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        if len(self.targets) != 1:
            raise BehaviorError(
                "The 'hint' behavior type only supports a single target."
            )

        target_ips = _resolve_target_ips(self.targets, build_context, service_name)
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
    Class represents behavior of Generating 'stub-zone' configuration for Unbound
    """

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        target_ips = _resolve_target_ips(self.targets, build_context, service_name)
        stub_addrs = "\n\t".join([f"stub-addr: {ip}" for ip in target_ips])
        config_line = f'stub-zone:\n\tname: "{self.zone}"\n\t{stub_addrs}'
        return BehaviorArtifact(config_line=config_line)


class UnboundMasterBehavior(MasterBehavior):
    """Generates `auth-zone` configuration for Unbound."""

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        return f'auth-zone:\n\tname: "{zone_name}"\n\tzonefile: "{file_path}"'

