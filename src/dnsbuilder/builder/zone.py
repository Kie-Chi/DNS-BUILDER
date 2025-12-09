import time
from typing import List, Dict
from dnslib import RR, SOA, A, NS, DNSLabel, QTYPE, CLASS
import logging
import hashlib

from ..datacls import BuildContext
from ..exceptions import NetworkDefinitionError

logger = logging.getLogger(__name__)

DEPTHS = {
    0 : "root-servers",
    1 : "tld-servers",
    2 : "sld-servers",
    # 3 or more is not supported, we just random
}

# Class-level counter per depth and per service
_zone_counters: Dict[int, int] = {}
_zone_prefixes: Dict[int, Dict[str, str]] = {}


def _gen_prefix(count: int) -> str:
    """
    Generate a unique identifier based on count.    
    - 0: 'ns'
    - 1-26: 'a' to 'z'
    - 27-52: 'aa' to 'az'
    - 53-78: 'ba' to 'bz'
    - etc.
    Args:
        count: The counter value (0-indexed)
    Returns:
        A unique string identifier
    """
    if count == 0:
        return "ns"
    
    # Adjust count to be 1-indexed for the alphabet pattern
    count = count - 1
    
    # Calculate how many letters we need
    result = []
    while True:
        result.append(chr(ord('a') + (count % 26)))
        count = count // 26
        if count == 0:
            break
        count -= 1  # Adjust for the next iteration
    return ''.join(reversed(result))


def _prefix(depth: int, service_name: str) -> str:
    """
    Get a stable prefix for a given depth and service name. Reuses the same
    prefix when the same service appears multiple times at the same depth.
    """
    service_key = service_name.rstrip(".")

    if depth not in _zone_prefixes:
        _zone_prefixes[depth] = {}

    if service_key in _zone_prefixes[depth]:
        return _zone_prefixes[depth][service_key]

    if depth not in _zone_counters:
        _zone_counters[depth] = 0
    else:
        _zone_counters[depth] += 1

    prefix = _gen_prefix(_zone_counters[depth])
    _zone_prefixes[depth][service_key] = prefix
    return prefix


def _reset() -> None:
    """
    Reset all zone counters.
    """
    global _zone_counters
    _zone_counters.clear()
    _zone_prefixes.clear()


class ZoneGenerator:
    """
    Generates the content for a DNS zone file using dnslib.
    """

    def __init__(self, context: BuildContext, zone_name: str, service_name: str, records: List[RR]):
        self.context = context
        self.zone_name = zone_name.rstrip(".") + "."
        self.ip = self.context.service_ips.get(service_name)
        if self.ip is None:
            raise NetworkDefinitionError(
                f"Service IP not found for {service_name}"
            )
        self.service_name = service_name.rstrip(".") + "."
        self.records = records

    def generate(self) -> str:
        """
        Creates the full zone file content, including SOA and NS records.
        """
        logger.debug(
            f"Generating zone file for '{self.zone_name}' with {len(self.records)} records."
        )

        # Generate a simple serial number based on the current timestamp
        serial = int(time.time())

        # Create default SOA and NS records
        depth = self.zone_name.count(".") if self.zone_name != "." else 0
        base_name = DEPTHS.get(depth, "servers")
        unique_id = _prefix(depth, self.service_name)
        ns_name = f"{unique_id}.{base_name}.net."
        soa_name = f"admin.{base_name}.net."
        
        default_records = [
            RR(
                rname=self.zone_name,
                rtype=QTYPE.SOA,
                rdata=SOA(
                    mname=ns_name,  # Primary master name
                    rname=soa_name,  # Responsible person
                    times=(
                        serial,  # Serial
                        7200,  # Refresh
                        3600,  # Retry
                        1209600,  # Expire
                        3600,  # Negative Cache TTL
                    ),
                ),
                ttl=86400,
            ),
            RR(
                rname=self.zone_name,
                rtype=QTYPE.NS,
                rdata=NS(ns_name),
                ttl=3600,
            ),
            RR(
                rname=ns_name,
                rtype=QTYPE.A,
                rdata=A(self.ip),
                ttl=3600,
            )
        ]

        # Add all user-defined records
        all_records = default_records + self.records

        # Format all records into a zone file string
        zone_content_parts = [f"$ORIGIN {self.zone_name}"]
        zone_label = DNSLabel(self.zone_name)

        for record in all_records:
            record_label = DNSLabel(record.rname)
            rname_str = ""

            if record_label == zone_label:
                rname_str = "@"
            elif str(record_label).endswith(str(zone_label)):
                relative_label_obj = record_label.stripSuffix(zone_label)
                rname_str = str(relative_label_obj).rstrip('.')
            else:
                rname_str = str(record_label)

            ttl_str = str(record.ttl) if record.ttl else ""
            rclass_str = CLASS.get(record.rclass, f"CLASS{record.rclass}")
            rtype_str = QTYPE.get(record.rtype, f"TYPE{record.rtype}")

            line = f"{rname_str:<24}{ttl_str:<8}{rclass_str:<8}{rtype_str:<8}{record.rdata.toZone()}"
            zone_content_parts.append(line)

        logger.debug(f"Finished generating zone file for '{self.zone_name}'.")
        return "\n".join(zone_content_parts)
