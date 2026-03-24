import time
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dnslib import RR, SOA, A, NS, DNSLabel, QTYPE, CLASS
import logging
import hashlib

from ..datacls import BuildContext
from ..datacls.artifacts import ZoneArtifact
from ..exceptions import NetworkDefinitionError
from ..io import DNSBPath
from ..auto.executor import ScriptExecutor
from ..utils.dnssec import get_dnssec_hooks, get_dnssec_includes

logger = logging.getLogger(__name__)


class ZoneGenerator:
    """
    Generates the content for a DNS zone file using dnslib.
    Supports DNSSEC signing with KSK and ZSK key generation.
    Supports DNSSEC hooks for vulnerability reproduction scenarios.
    Supports including pre-generated keys from external directories.
    """

    def __init__(
        self,
        context: BuildContext,
        zone_name: str,
        service_name: str,
        records: List[RR],
        enable_dnssec: bool = False,
        build_conf: Optional[Dict[str, Any]] = None
    ):
        self.context = context
        self.zone_name = zone_name.rstrip(".") + "."
        self.ip = self.context.service_ips.get(service_name)
        if self.ip is None:
            raise NetworkDefinitionError(
                f"Service IP not found for {service_name}"
            )
        self.service_name = service_name.rstrip(".") + "."
        self.service_name_raw = service_name
        self.records = records
        self.enable_dnssec = enable_dnssec
        self.build_conf = build_conf or {}
        self.dnssec_hooks = get_dnssec_hooks(self.build_conf) if enable_dnssec else {}
        self.dnssec_includes = get_dnssec_includes(self.build_conf) if enable_dnssec else []
        self._executor = ScriptExecutor(fs=context.fs) if self.dnssec_hooks else None

    def _find_keys_in_include(self, temp_path: Path) -> Optional[Tuple[str, str, str, str, str, str]]:
        """
        Try to find KSK/ZSK keys from include directories.
        Looks for files matching patterns:
        - *.ksk.key, *.ksk.private (KSK)
        - *.zsk.key, *.zsk.private (ZSK)
        Args:
            temp_path: Temporary directory to copy keys to
        """
        fs = self.context.fs

        logger.debug(f"[DNSSEC] Searching for keys in {len(self.dnssec_includes)} include directorie(s)")

        for include_path in self.dnssec_includes:
            try:
                key_dir = DNSBPath(include_path)
                logger.debug(f"[DNSSEC] Checking include directory: {key_dir}")

                if not fs.exists(key_dir):
                    logger.debug(f"[DNSSEC] Include directory not found: {key_dir}")
                    continue

                # Find KSK files
                ksk_key_files = list(fs.glob(key_dir, "*.ksk.key"))
                ksk_private_files = list(fs.glob(key_dir, "*.ksk.private"))
                logger.debug(f"[DNSSEC] Pattern '*.ksk.key' found: {len(ksk_key_files)} file(s) - {[f.name for f in ksk_key_files]}")
                logger.debug(f"[DNSSEC] Pattern '*.ksk.private' found: {len(ksk_private_files)} file(s) - {[f.name for f in ksk_private_files]}")

                # Find ZSK files
                zsk_key_files = list(fs.glob(key_dir, "*.zsk.key"))
                zsk_private_files = list(fs.glob(key_dir, "*.zsk.private"))
                logger.debug(f"[DNSSEC] Pattern '*.zsk.key' found: {len(zsk_key_files)} file(s) - {[f.name for f in zsk_key_files]}")
                logger.debug(f"[DNSSEC] Pattern '*.zsk.private' found: {len(zsk_private_files)} file(s) - {[f.name for f in zsk_private_files]}")

                # Also try standard BIND format: K<zone>.+<alg>+<keytag>.key
                if not ksk_key_files or not zsk_key_files:
                    logger.debug(f"[DNSSEC] Trying BIND standard format...")
                    all_key_files = list(fs.glob(key_dir, "*.key"))
                    all_private_files = list(fs.glob(key_dir, "*.private"))
                    logger.debug(f"[DNSSEC] Pattern '*.key' found: {len(all_key_files)} file(s) - {[f.name for f in all_key_files]}")
                    logger.debug(f"[DNSSEC] Pattern '*.private' found: {len(all_private_files)} file(s) - {[f.name for f in all_private_files]}")

                    for key_file in all_key_files:
                        key_content = fs.read_text(key_file)
                        # KSK has flag 257, ZSK has flag 256
                        # BIND format: "domain. IN DNSKEY 257 3 13 <base64>"
                        is_ksk = False
                        is_zsk = False

                        # Check for flags in DNSKEY record line
                        for line in key_content.split("\n"):
                            line = line.strip()
                            if "DNSKEY" in line and ("257" in line or "256" in line):
                                if "257" in line:
                                    is_ksk = True
                                    break
                                elif "256" in line:
                                    is_zsk = True
                                    break

                        # Also check for comment-style flags
                        if not is_ksk and not is_zsk:
                            if "; flags:257" in key_content or "; KSK" in key_content.upper():
                                is_ksk = True
                            elif "; flags:256" in key_content or "; ZSK" in key_content.upper():
                                is_zsk = True

                        if is_ksk and not ksk_key_files:
                            ksk_key_files = [key_file]
                            logger.debug(f"[DNSSEC] Identified KSK by flags: {key_file.name}")
                        elif is_zsk and not zsk_key_files:
                            zsk_key_files = [key_file]
                            logger.debug(f"[DNSSEC] Identified ZSK by flags: {key_file.name}")

                    # Match private files with key files by name
                    ksk_key_names = {f.name.replace('.key', '') for f in ksk_key_files}
                    zsk_key_names = {f.name.replace('.key', '') for f in zsk_key_files}

                    for private_file in all_private_files:
                        base_name = private_file.name.replace('.private', '')
                        if base_name in ksk_key_names:
                            ksk_private_files = [private_file]
                            logger.debug(f"[DNSSEC] Matched KSK private: {private_file.name}")
                        elif base_name in zsk_key_names:
                            zsk_private_files = [private_file]
                            logger.debug(f"[DNSSEC] Matched ZSK private: {private_file.name}")

                # Check if we have all required files
                logger.debug(f"[DNSSEC] Key search result for {key_dir}:")
                logger.debug(f"[DNSSEC]   KSK key: {ksk_key_files[0].name if ksk_key_files else 'NOT FOUND'}")
                logger.debug(f"[DNSSEC]   KSK private: {ksk_private_files[0].name if ksk_private_files else 'NOT FOUND'}")
                logger.debug(f"[DNSSEC]   ZSK key: {zsk_key_files[0].name if zsk_key_files else 'NOT FOUND'}")
                logger.debug(f"[DNSSEC]   ZSK private: {zsk_private_files[0].name if zsk_private_files else 'NOT FOUND'}")

                if ksk_key_files and ksk_private_files and zsk_key_files and zsk_private_files:
                    ksk_key = ksk_key_files[0]
                    ksk_private = ksk_private_files[0]
                    zsk_key = zsk_key_files[0]
                    zsk_private = zsk_private_files[0]

                    # Read key contents
                    ksk_key_content = fs.read_text(ksk_key)
                    ksk_private_content = fs.read_text(ksk_private)
                    zsk_key_content = fs.read_text(zsk_key)
                    zsk_private_content = fs.read_text(zsk_private)

                    # Keep original filenames for BIND format compatibility
                    # dnssec-signzone expects K<zone>.+<alg>+<keytag>.key/.private format
                    ksk_basename = ksk_key.name.replace('.key', '')
                    zsk_basename = zsk_key.name.replace('.key', '')

                    (temp_path / f"{ksk_basename}.key").write_text(ksk_key_content)
                    (temp_path / f"{ksk_basename}.private").write_text(ksk_private_content)
                    (temp_path / f"{zsk_basename}.key").write_text(zsk_key_content)
                    (temp_path / f"{zsk_basename}.private").write_text(zsk_private_content)

                    logger.info(f"[DNSSEC] Using keys from include directory: {key_dir}")
                    logger.info(f"[DNSSEC] KSK: {ksk_key.name}, ZSK: {zsk_key.name}")

                    return (ksk_key_content, ksk_private_content, zsk_key_content,
                            zsk_private_content, ksk_basename, zsk_basename)
                else:
                    logger.debug(f"[DNSSEC] Incomplete key set in {key_dir}, skipping")

            except Exception as e:
                logger.warning(f"[DNSSEC] Error reading keys from {include_path}: {e}")
                continue

        logger.debug(f"[DNSSEC] No valid keys found in any include directory")
        return None

    def _execute_hook(
        self,
        hook_name: str,
        hook_vars: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a DNSSEC hook script and return the modified namespace.

        Args:
            hook_name: Name of the hook (e.g., 'pre-sign', 'post-sign')
            hook_vars: Additional variables to pass to the hook script
        """
        hook_script = self.dnssec_hooks.get(hook_name)
        if not hook_script:
            return hook_vars or {}

        logger.info(f"[DNSSEC-Hook] Executing {hook_name} hook for zone '{self.zone_name}'")

        # Prepare variables for the hook script
        zone_name_clean = self.zone_name.rstrip('.')
        zone_name_clean = zone_name_clean if zone_name_clean != '.' else 'root'

        globals_dict = {
            'zone_name': self.zone_name,
            'zone_name_clean': zone_name_clean,
            'service_name': self.service_name_raw,
            'fs': self.context.fs,
            'workdir': self.context.fs.chroot,
            'config': self.build_conf,
            **(hook_vars or {})
        }

        try:
            exec(hook_script, globals_dict)
            logger.info(f"[DNSSEC-Hook] {hook_name} hook completed for zone '{self.zone_name}'")
            return globals_dict
        except Exception as e:
            logger.error(f"[DNSSEC-Hook] {hook_name} hook failed for zone '{self.zone_name}': {e}")
            logger.exception(e)
            raise

    def _sign_zone(self, unsigned_content: str) -> Optional[Tuple[str, str, str, str, str, str, str, str]]:
        # Execute pre hook before signing
        hook_result = self._execute_hook('pre', {
            'unsigned_content': unsigned_content,
            'temp_path': None  # Will be set inside temp context if needed
        })
        unsigned_content = hook_result.get('unsigned_content', unsigned_content)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                zone_filename = f"db.{self.zone_name.rstrip('.')}" if self.zone_name != "." else "db.root"
                unsigned_file = temp_path / zone_filename
                unsigned_file.write_text(unsigned_content)

                # Try to use keys from include directory first
                included_keys = self._find_keys_in_include(temp_path)

                if included_keys:
                    # Use pre-generated keys from include directory
                    ksk_key_content, ksk_private_content, zsk_key_content, zsk_private_content, ksk_basename, zsk_basename = included_keys
                    logger.info(f"[DNSSEC] Using included keys for '{self.zone_name}'")
                else:
                    # Fallback: generate new keys
                    if self.dnssec_includes:
                        logger.warning(f"[DNSSEC] No valid keys found in include directories, falling back to auto-generation for '{self.zone_name}'")

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
                    zsk_private_content = zsk_private_file.read_text()
                    ksk_key_content = ksk_key_file.read_text()
                    ksk_private_content = ksk_private_file.read_text()

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
                zone_name_clean = self.zone_name.rstrip('.')
                dsset_file = temp_path / f"dsset-{zone_name_clean}."
                ds_content = ""
                if dsset_file.exists():
                    ds_content = dsset_file.read_text()
                    logger.debug(f"Found DS records for '{self.zone_name}'")
                else:
                    logger.warning(f"DS record file not found: {dsset_file}")

                logger.debug(f"DNSSEC signing succeeded for '{self.zone_name}'")

                return (signed_content, ksk_key_content, zsk_key_content, ds_content,
                        ksk_private_content, zsk_private_content, ksk_basename, zsk_basename)

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

        # Create default SOA and NS records using service name
        # Format: {service}.servers.net. (e.g., root.servers.net., tld.servers.net.)
        service_prefix = self.service_name.rstrip(".")
        ns_name = f"{service_prefix}.servers.net."
        soa_name = "admin.servers.net."
        
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
        signed_content, ksk_content, zsk_content, ds_content, ksk_private_content, zsk_private_content, ksk_basename, zsk_basename = sign_result
        logger.debug(f"DNSSEC signing successful for '{self.zone_name}', generating artifacts.")
        
        zone_name_clean = self.zone_name.rstrip('.')
        zone_name_clean = zone_name_clean if zone_name_clean != '.' else 'root'
        
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
            ),
            # DS record set file
            ZoneArtifact(
                filename=f"dsset-{zone_name_clean}",
                content=ds_content,
                container_path=f"/usr/local/etc/zones/keys/dsset-{zone_name_clean}",
                is_primary=False
            )
        ]
        self.context.fs.mkdir(DNSBPath(f"key:/{self.service_name.rstrip('.')}"), exist_ok=True)
        self.context.fs.write_text(DNSBPath(f"key:/{self.service_name.rstrip('.')}/{zone_name_clean}.ksk.key"), ksk_content)
        self.context.fs.write_text(DNSBPath(f"key:/{self.service_name.rstrip('.')}/{zone_name_clean}.ksk.private"), ksk_private_content)
        self.context.fs.write_text(DNSBPath(f"key:/{self.service_name.rstrip('.')}/{zone_name_clean}.zsk.key"), zsk_content)
        self.context.fs.write_text(DNSBPath(f"key:/{self.service_name.rstrip('.')}/{zone_name_clean}.zsk.private"), zsk_private_content)
        self.context.fs.write_text(DNSBPath(f"key:/{self.service_name.rstrip('.')}/{zone_name_clean}.ds"), ds_content)
        # Save key basenames for re-signing (e.g., "K.+013+61193")
        # This metadata is needed to recreate proper key filenames during re-signing
        key_metadata = f"KSK_BASENAME={ksk_basename}\nZSK_BASENAME={zsk_basename}\n"
        self.context.fs.write_text(DNSBPath(f"key:/{self.service_name.rstrip('.')}/{zone_name_clean}.keynames"), key_metadata)
        
        return artifacts
