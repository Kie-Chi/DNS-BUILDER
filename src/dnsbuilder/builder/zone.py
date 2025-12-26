import time
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dnslib import RR, SOA, A, NS, DNSLabel, QTYPE, CLASS
import logging
import hashlib

from ..datacls import BuildContext
from ..datacls.artifacts import ZoneArtifact
from ..exceptions import NetworkDefinitionError
from ..io import DNSBPath

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
    Supports DNSSEC signing with KSK and ZSK key generation.
    """

    def __init__(self, context: BuildContext, zone_name: str, service_name: str, records: List[RR], enable_dnssec: bool = False):
        self.context = context
        self.zone_name = zone_name.rstrip(".") + "."
        self.ip = self.context.service_ips.get(service_name)
        if self.ip is None:
            raise NetworkDefinitionError(
                f"Service IP not found for {service_name}"
            )
        self.service_name = service_name.rstrip(".") + "."
        self.records = records
        self.enable_dnssec = enable_dnssec

    def _sign_zone(self, unsigned_content: str) -> Optional[Tuple[str, str, str]]:
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                zone_filename = f"db.{self.zone_name.rstrip('.')}" if self.zone_name != "." else "db.root"
                unsigned_file = temp_path / zone_filename
                unsigned_file.write_text(unsigned_content)
                logger.debug(f"Generating ZSK for '{self.zone_name}' using dnssec-keygen")
                zsk_result = subprocess.run(
                    ["dnssec-keygen", "-a", "ECDSAP256SHA256", "-n", "ZONE", self.zone_name],
                    cwd=temp_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                zsk_basename = zsk_result.stdout.strip()
                logger.debug(f"Generated ZSK: {zsk_basename}")
                
                logger.debug(f"Generating KSK for '{self.zone_name}' using dnssec-keygen")
                ksk_result = subprocess.run(
                    ["dnssec-keygen", "-a", "ECDSAP256SHA256", "-f", "KSK", "-n", "ZONE", self.zone_name],
                    cwd=temp_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                ksk_basename = ksk_result.stdout.strip()
                logger.debug(f"Generated KSK: {ksk_basename}")
                zsk_key_file = temp_path / f"{zsk_basename}.key"
                zsk_private_file = temp_path / f"{zsk_basename}.private"
                ksk_key_file = temp_path / f"{ksk_basename}.key"
                ksk_private_file = temp_path / f"{ksk_basename}.private"

                if not all([zsk_key_file.exists(), zsk_private_file.exists(), 
                           ksk_key_file.exists(), ksk_private_file.exists()]):
                    logger.error(f"Key files not found in {temp_path}")
                    logger.error(f"ZSK key: {zsk_key_file.exists()}, ZSK private: {zsk_private_file.exists()}")
                    logger.error(f"KSK key: {ksk_key_file.exists()}, KSK private: {ksk_private_file.exists()}")
                    return None
                
                zsk_key_content = zsk_key_file.read_text()
                ksk_key_content = ksk_key_file.read_text()
                # append keys
                unsigned_file.write_text(
                    unsigned_file.read_text() + "\n" +
                    f"$INCLUDE {zsk_basename}.key\n" +
                    f"$INCLUDE {ksk_basename}.key\n"
                )

                logger.debug(f"Signing zone '{self.zone_name}' using dnssec-signzone")
                sign_result = subprocess.run(
                    [
                        "dnssec-signzone",
                        "-3", hashlib.sha1(self.zone_name.encode()).hexdigest()[:16], 
                        "-N", "INCREMENT",
                        "-o", self.zone_name,
                        str(unsigned_file),
                    ],
                    cwd=temp_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                logger.debug(f"dnssec-signzone output: {sign_result.stdout}")
                signed_file = temp_path / f"{zone_filename}.signed"
                if not signed_file.exists():
                    logger.error(f"Signed zone file not found: {signed_file}")
                    return None
                
                signed_content = signed_file.read_text()
                logger.debug(f"DNSSEC signing succeeded for '{self.zone_name}'")
                
                return (signed_content, ksk_key_content, zsk_key_content)
                
        except subprocess.CalledProcessError as e:
            logger.error(f"DNSSEC command failed for '{self.zone_name}': {e.stderr}")
            return None
        except FileNotFoundError as e:
            logger.error(f"DNSSEC tools not found. Please install bind9-dnsutils: {e}")
            return None
        except Exception as e:
            logger.error(f"DNSSEC signing failed for '{self.zone_name}': {e}")
            logger.exception(e)
            return None

    def generate(self) -> List[ZoneArtifact]:
        """
        Creates the full zone file content, including SOA and NS records.
        
        Returns:
            List[ZoneArtifact]: List of generated zone file artifacts.
        """
        logger.debug(
            f"Generating zone file for '{self.zone_name}' with {len(self.records)} records (DNSSEC: {self.enable_dnssec})."
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

        # First pass: calculate the maximum domain name length
        max_rname_len = 0
        formatted_records = []
        
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

            max_rname_len = max(max_rname_len, len(rname_str))
            
            ttl_str = str(record.ttl) if record.ttl else ""
            rclass_str = CLASS.get(record.rclass, f"CLASS{record.rclass}")
            rtype_str = QTYPE.get(record.rtype, f"TYPE{record.rtype}")
            
            formatted_records.append((rname_str, ttl_str, rclass_str, rtype_str, record.rdata.toZone()))
        
        # Use dynamic width based on the longest domain name, minimum 24
        rname_width = max(24, max_rname_len + 4)
        
        # Second pass: format all records with consistent width
        for rname_str, ttl_str, rclass_str, rtype_str, rdata in formatted_records:
            line = f"{rname_str:<{rname_width}}{ttl_str:<8}{rclass_str:<8}{rtype_str:<8}{rdata}"
            zone_content_parts.append(line)

        unsigned_content = "\n".join(zone_content_parts)
        logger.debug(f"Finished generating unsigned zone file for '{self.zone_name}'.")
        base_filename = f"db.{self.zone_name.rstrip('.')}" if self.zone_name != "." else "db.root"
        if not self.enable_dnssec:
            return [
                ZoneArtifact(
                    filename=base_filename,
                    content=unsigned_content,
                    container_path=f"/usr/local/etc/zones/{base_filename}",
                    is_primary=True
                )
            ]
        sign_result = self._sign_zone(unsigned_content)
        if not sign_result:
            logger.warning(f"DNSSEC signing failed for '{self.zone_name}', falling back to unsigned.")
            return [
                ZoneArtifact(
                    filename=base_filename,
                    content=unsigned_content,
                    container_path=f"/usr/local/etc/zones/{base_filename}",
                    is_primary=True
                )
            ]
        signed_content, ksk_content, zsk_content = sign_result
        logger.debug(f"DNSSEC signing successful for '{self.zone_name}', generating artifacts.")
        zone_name_clean = self.zone_name.rstrip('.')
        artifacts = [
            # Signed zone file
            ZoneArtifact(
                filename=base_filename,
                content=signed_content,
                container_path=f"/usr/local/etc/zones/{base_filename}",
                is_primary=True
            ),
            # Unsigned zone file
            ZoneArtifact(
                filename=f"{base_filename}.unsigned",
                content=unsigned_content,
                container_path=f"/usr/local/etc/zones/{base_filename}.unsigned",
                is_primary=False
            ),
            # KSK key file
            ZoneArtifact(
                filename=f"K{zone_name_clean}.ksk.key",
                content=ksk_content,
                container_path=f"/usr/local/etc/zones/keys/K{zone_name_clean}.ksk.key",
                is_primary=False
            ),
            # ZSK key file
            ZoneArtifact(
                filename=f"K{zone_name_clean}.zsk.key",
                content=zsk_content,
                container_path=f"/usr/local/etc/zones/keys/K{zone_name_clean}.zsk.key",
                is_primary=False
            )
        ]
        return artifacts
