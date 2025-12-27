import logging
from typing import List
import dns.rdata
import dns.rdatatype
import dns.rdataclass
from ..datacls import BuildContext
from ..io import DNSBPath

logger = logging.getLogger(__name__)


class DNSSECHandler:
    """
    Handles DNSSEC key operations after all services complete behavior processing.
    
    This handler is invoked once after the barrier synchronization point to perform
    global DNSSEC operations that require all zone files and keys to be generated.
    """
    
    def __init__(self, context: BuildContext):
        """
        Initialize the DNSSEC handler.
        
        Args:
            context: Build context containing file system and service information
        """
        self.context = context
        self.fs = context.fs
        
    def run(self) -> None:
        """
        Main entry point for DNSSEC processing.
        
        This method is called by the barrier action callback after all services
        have completed their behavior processing. It executes all DNSSEC operations
        in sequence.
        """
        logger.info("[DNSSEC] Starting DNSSEC key processing...")
        
        try:
            # Combine all KSK keys into a single file
            self._combine_ksk_keys()
            
            # Combine all DS records into a single file
            self._combine_ds_records()
            
            # Generate BIND trusted-keys format
            self._gen_bind_keys()
            
            # Generate PowerDNS trust anchors format
            self._gen_pdns_trustanchors()
            
            # Future operations can be added here:
            # self._generate_trust_anchors()
            # self._validate_key_chain()
            
            logger.info("[DNSSEC] DNSSEC key processing completed successfully.")
        except Exception as e:
            logger.error(f"[DNSSEC] Error during DNSSEC processing: {e}")
            # Log the error but don't raise to avoid breaking the barrier
            # Services can continue even if DNSSEC processing fails
    
    def _combine_ksk_keys(self) -> None:
        """
        Combine all KSK keys from key:/ into a single file.
        
        This method scans the key:/ protocol path for all *.ksk.key files,
        reads their contents, and combines them into key:/combined.ksk.key.
        This combined file can be used as a trust anchor file for recursive resolvers.
        """
        logger.debug("[DNSSEC] Combining KSK keys...")
        
        # Find all KSK key files under key:/
        ksk_files = self._find_ksk_files()
        
        if not ksk_files:
            logger.warning("[DNSSEC] No KSK key files found in key:/. Skipping combination.")
            return
        
        logger.info(f"[DNSSEC] Found {len(ksk_files)} KSK key file(s): {ksk_files}")
        
        # Read and combine all KSK key contents
        combined_content = []
        for ksk_file in ksk_files:
            try:
                content = self.fs.read_text(ksk_file)
                if content.strip():  # Only add non-empty content
                    combined_content.append(content.strip())
                    logger.debug(f"[DNSSEC] Read KSK key from {ksk_file}")
            except Exception as e:
                logger.warning(f"[DNSSEC] Failed to read {ksk_file}: {e}")
        
        if not combined_content:
            logger.warning("[DNSSEC] All KSK key files were empty or unreadable.")
            return
        
        # Write combined content to key:/all.ksk.key
        output_path = DNSBPath("key:/all.ksk.key")
        combined_text = "\n\n".join(combined_content) + "\n"
        
        try:
            self.fs.write_text(output_path, combined_text)
            logger.info(f"[DNSSEC] Successfully combined {len(combined_content)} KSK key(s) into {output_path}")
            logger.debug(f"[DNSSEC] Combined file size: {len(combined_text)} bytes")
        except Exception as e:
            logger.error(f"[DNSSEC] Failed to write combined KSK file to {output_path}: {e}")
    
    def _find_ksk_files(self) -> List[DNSBPath]:
        """
        Find all KSK key files in the key:/ protocol path.
        
        Returns:
            List of DNSBPath objects pointing to *.ksk.key files
        """
        key_root = DNSBPath("key:/")
        
        try:
            # Check if key:/ exists
            if not self.fs.exists(key_root):
                logger.debug("[DNSSEC] key:/ path does not exist")
                return []
            
            # Use rglob to recursively find all .ksk.key files
            # Using *ksk.key to match files like .ksk.key, K{zone}.ksk.key, etc.
            ksk_files = self.fs.rglob(key_root, "*ksk.key")
            logger.debug(f"[DNSSEC] rglob found {len(ksk_files)} KSK key file(s): {[str(f) for f in ksk_files]}")
            return ksk_files
            
        except Exception as e:
            logger.warning(f"[DNSSEC] Error scanning key:/ for KSK files: {e}")
            return []
    
    def _combine_ds_records(self) -> None:
        """
        Combine all DS records from key:/ into a single file.
        
        This method scans the key:/ protocol path for all *.ds files,
        reads their contents, and combines them into key:/all.ds.
        This combined file can be used for delegating zones to parent servers.
        """
        logger.debug("[DNSSEC] Combining DS records...")
        
        # Find all DS record files under key:/
        ds_files = self._find_ds_files()
        
        if not ds_files:
            logger.warning("[DNSSEC] No DS record files found in key:/. Skipping combination.")
            return
        
        logger.info(f"[DNSSEC] Found {len(ds_files)} DS record file(s): {ds_files}")
        
        # Read and combine all DS record contents
        combined_content = []
        for ds_file in ds_files:
            try:
                content = self.fs.read_text(ds_file)
                if content.strip():  # Only add non-empty content
                    combined_content.append(content.strip())
                    logger.debug(f"[DNSSEC] Read DS record from {ds_file}")
            except Exception as e:
                logger.warning(f"[DNSSEC] Failed to read {ds_file}: {e}")
        
        if not combined_content:
            logger.warning("[DNSSEC] All DS record files were empty or unreadable.")
            return
        
        # Write combined content to key:/all.ds
        output_path = DNSBPath("key:/all.ds")
        combined_text = "\n\n".join(combined_content) + "\n"
        
        try:
            self.fs.write_text(output_path, combined_text)
            logger.info(f"[DNSSEC] Successfully combined {len(combined_content)} DS record(s) into {output_path}")
            logger.debug(f"[DNSSEC] Combined DS file size: {len(combined_text)} bytes")
        except Exception as e:
            logger.error(f"[DNSSEC] Failed to write combined DS file to {output_path}: {e}")
    
    def _find_ds_files(self) -> List[DNSBPath]:
        """
        Find all DS record files in the key:/ protocol path.
        
        Returns:
            List of DNSBPath objects pointing to *.ds files
        """
        key_root = DNSBPath("key:/")
        
        try:
            # Check if key:/ exists
            if not self.fs.exists(key_root):
                logger.debug("[DNSSEC] key:/ path does not exist")
                return []
            
            # Use rglob to recursively find all .ds files
            ds_files = self.fs.rglob(key_root, "*.ds")
            logger.debug(f"[DNSSEC] rglob found {len(ds_files)} DS record file(s): {[str(f) for f in ds_files]}")
            return ds_files
            
        except Exception as e:
            logger.warning(f"[DNSSEC] Error scanning key:/ for DS files: {e}")
            return []
    
    def _gen_bind_keys(self) -> None:
        """
        Generate BIND trusted-keys format from combined KSK keys.
        
        Reads key:/all.ksk.key and converts DNSKEY records to BIND's trusted-keys
        format, writing the result to key:/all.ksk.key.bind.
        
        Uses dnspython to properly parse DNSKEY records.
        """
        logger.debug("[DNSSEC] Generating BIND trusted-keys format...")
        
        combined_key_path = DNSBPath("key:/all.ksk.key")
        
        # Check if combined key file exists
        if not self.fs.exists(combined_key_path):
            logger.warning("[DNSSEC] Combined key file key:/all.ksk.key not found. Skipping BIND format generation.")
            return
        
        try:
            # Read combined key file
            content = self.fs.read_text(combined_key_path)
            
            # Parse DNSKEY records and convert to trusted-keys format
            trusted_keys_entries = []
            
            for line in content.strip().split('\n'):
                line = line.strip()
                if not line or line.startswith(';') or line.startswith('#'):
                    # Skip empty lines and comments
                    continue
                
                if 'DNSKEY' in line:
                    try:
                        # Parse DNSKEY record using dnspython
                        # Format: zone. IN DNSKEY flags protocol algorithm key_data
                        parts = line.split()
                        
                        if len(parts) < 7:
                            logger.warning(f"[DNSSEC] Skipping malformed DNSKEY line: {line}")
                            continue
                        
                        zone = parts[0].rstrip('.')
                        # parts[1] = IN (class)
                        # parts[2] = DNSKEY
                        
                        # Join the DNSKEY record data (from flags onwards)
                        rdata_text = ' '.join(parts[3:])
                        
                        # Parse using dnspython
                        dnskey_rdata = dns.rdata.from_text(
                            dns.rdataclass.IN,
                            dns.rdatatype.DNSKEY,
                            rdata_text
                        )
                        
                        # Extract fields from parsed DNSKEY
                        flags = dnskey_rdata.flags
                        protocol = dnskey_rdata.protocol
                        algorithm = dnskey_rdata.algorithm
                        # Convert key to base64 string
                        import base64
                        key_data = base64.b64encode(dnskey_rdata.key).decode('ascii')
                        
                        # Generate trusted-keys entry
                        # Format: "zone" flags protocol algorithm "key_data";
                        trusted_key_entry = f'    "{zone}." {flags} {protocol} {algorithm} "{key_data}";'
                        trusted_keys_entries.append(trusted_key_entry)
                        logger.debug(f"[DNSSEC] Converted DNSKEY for zone {zone}")
                        
                    except Exception as e:
                        logger.warning(f"[DNSSEC] Failed to parse DNSKEY line '{line}': {e}")
                        continue
            
            if not trusted_keys_entries:
                logger.warning("[DNSSEC] No valid DNSKEY records found in combined key file.")
                return
            
            # Wrap entries in trusted-keys block
            trusted_keys_content = '\n'.join(trusted_keys_entries)
            
            # Write to key:/all.ksk.key.bind
            output_path = DNSBPath("key:/all.ksk.key.bind")
            self.fs.write_text(output_path, trusted_keys_content)
            
            logger.info(f"[DNSSEC] Generated BIND trusted-keys format with {len(trusted_keys_entries)} key(s) in {output_path}")
            logger.debug(f"[DNSSEC] Trusted-keys file size: {len(trusted_keys_content)} bytes")
            
        except Exception as e:
            logger.error(f"[DNSSEC] Failed to generate BIND trusted-keys format: {e}")
    
    def _gen_pdns_trustanchors(self) -> None:
        """
        Generate PowerDNS trust anchors configuration from combined DS records.
        
        Reads key:/all.ds and converts it to PowerDNS YAML format with trustanchors
        configuration. The output is written to key:/all.ds.pdns.
        
        PowerDNS format:
        dnssec:
          trustanchors:
            - name: '.'
              dsrecords:
                - 'keytag algorithm digesttype digest'
            - name: 'example.com'
              dsrecords:
                - 'keytag algorithm digesttype digest'
        """
        logger.debug("[DNSSEC] Generating PowerDNS trust anchors format...")
        
        combined_ds_path = DNSBPath("key:/all.ds")
        
        # Check if combined DS file exists
        if not self.fs.exists(combined_ds_path):
            logger.warning("[DNSSEC] Combined DS file key:/all.ds not found. Skipping PowerDNS format generation.")
            return
        
        try:
            # Read combined DS file
            content = self.fs.read_text(combined_ds_path)
            
            # Parse DS records and group by zone name
            from collections import defaultdict
            zone_ds_map = defaultdict(list)
            
            for line in content.strip().split('\n'):
                line = line.strip()
                if not line or line.startswith(';') or line.startswith('#'):
                    # Skip empty lines and comments
                    continue
                
                if 'DS' in line:
                    try:
                        # Parse DS record
                        # Format: zone. TTL IN DS keytag algorithm digesttype digest
                        parts = line.split()
                        
                        if len(parts) < 8:
                            logger.warning(f"[DNSSEC] Skipping malformed DS line: {line}")
                            continue
                        
                        zone = parts[0].rstrip('.')
                        # parts[1] = TTL
                        # parts[2] = IN (class)
                        # parts[3] = DS
                        keytag = parts[4]
                        algorithm = parts[5]
                        digesttype = parts[6]
                        digest = parts[7]
                        
                        # Build DS record string: 'keytag algorithm digesttype digest'
                        ds_entry = f'{keytag} {algorithm} {digesttype} {digest}'
                        zone_ds_map[zone].append(ds_entry)
                        logger.debug(f"[DNSSEC] Parsed DS record for zone {zone}: {ds_entry}")
                        
                    except Exception as e:
                        logger.warning(f"[DNSSEC] Failed to parse DS line '{line}': {e}")
                        continue
            
            if not zone_ds_map:
                logger.warning("[DNSSEC] No valid DS records found in combined DS file.")
                return
            
            # Generate PowerDNS YAML format
            yaml_lines = ["dnssec:", "  trustanchors:"]
            
            for zone, ds_records in sorted(zone_ds_map.items()):
                yaml_lines.append(f"    - name: '{zone}.'")
                yaml_lines.append("      dsrecords:")
                for ds_record in ds_records:
                    yaml_lines.append(f"        - '{ds_record}'")
            
            yaml_content = "\n".join(yaml_lines) + "\n"
            
            # Write to key:/all.ds.pdns
            output_path = DNSBPath("key:/all.ds.pdns")
            self.fs.write_text(output_path, yaml_content)
            
            logger.info(f"[DNSSEC] Successfully generated PowerDNS trust anchors format: {output_path}")
            logger.debug(f"[DNSSEC] PowerDNS config includes {len(zone_ds_map)} zone(s)")
        except Exception as e:
            logger.error(f"[DNSSEC] Failed to generate PowerDNS trust anchors format: {e}")
