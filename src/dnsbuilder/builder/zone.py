import time
from typing import List
from ..datacls.contexts import BuildContext
from dnslib import RR, SOA, A, NS, DNSLabel, QTYPE, CLASS
import logging
import hashlib
from ..exceptions import NetworkDefinitionError

logger = logging.getLogger(__name__)

DEPTHS = {
    0 : "root-servers",
    1 : "tld-servers",
    2 : "sld-servers",
    # 3 or more is not supported, we just random
}


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

    def generate_zone_file(self) -> str:
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
        used_name = DEPTHS[depth] if depth in DEPTHS else f"{hashlib.sha256(self.zone_name.encode()).hexdigest()[:16]}-servers"
        ns_name = f"ns.{used_name}.net."
        soa_name = f"admin.{used_name}.net."
        
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
