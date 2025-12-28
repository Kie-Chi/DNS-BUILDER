import logging
from typing import List, Dict, Optional, Tuple
import dns.rdata
import dns.rdatatype
import dns.rdataclass
import subprocess
import tempfile
import hashlib
from pathlib import Path
from ..datacls import BuildContext
from ..io import DNSBPath

logger = logging.getLogger(__name__)


class DNSSECResigner:
    """
    Handles DNSSEC re-signing operations to establish trust chain.
    
    This class analyzes zone dependencies, injects DS records from child zones
    into parent zones, and re-signs parent zones to complete the DNSSEC chain.
    """
    
    def __init__(self, context: BuildContext):
        """
        Initialize the DNSSEC re-signer.
        
        Args:
            context: Build context containing file system and service information
        """
        self.context = context
        self.fs = context.fs
        
    def run(self) -> None:
        """
        Main entry point for DNSSEC re-signing.
        
        Builds zone dependency graph, determines signing order, and re-signs
        parent zones with child DS records.
        """
        logger.info("[DNSSEC-Resigner] Starting DNSSEC re-signing process...")
        
        try:
            # Step 1: Build zone dependency graph
            zone_graph = self._bld_deps()
            
            if not zone_graph:
                logger.warning("[DNSSEC-Resigner] No zones found for re-signing.")
                return
            
            logger.info(f"[DNSSEC-Resigner] Built dependency graph with {len(zone_graph)} zone(s)")
            logger.debug(f"[DNSSEC-Resigner] Zone graph: {zone_graph}")
            
            # Step 2: Topologically sort zones (children first, parents last)
            sorted_zones = self._topological_sort(zone_graph)
            
            if not sorted_zones:
                logger.warning("[DNSSEC-Resigner] No parent zones found for re-signing.")
                return
            
            logger.info(f"[DNSSEC-Resigner] Will re-sign {len(sorted_zones)} parent zone(s): {sorted_zones}")
            
            # Step 3: Re-sign each parent zone with child DS records
            success_count = 0
            skip_count = 0
            
            for parent_zone in sorted_zones:
                zone_info = zone_graph[parent_zone]
                
                # Performance optimization: skip zones without children
                if not zone_info['children']:
                    logger.debug(f"[DNSSEC-Resigner] Skipping leaf zone '{parent_zone}' (no children)")
                    skip_count += 1
                    continue
                
                logger.info(f"[DNSSEC-Resigner] Re-signing parent zone '{parent_zone}' with {len(zone_info['children'])} child DS record(s)")
                
                if self._resign_parent_zone(parent_zone, zone_graph):
                    success_count += 1
                    logger.info(f"[DNSSEC-Resigner] Successfully re-signed '{parent_zone}'")
                else:
                    logger.warning(f"[DNSSEC-Resigner] Failed to re-sign '{parent_zone}'")
            
            logger.info(f"[DNSSEC-Resigner] Re-signing completed: {success_count} success, {skip_count} skipped (leaf zones)")
            
        except Exception as e:
            logger.error(f"[DNSSEC-Resigner] Error during DNSSEC re-signing: {e}")
            logger.exception(e)
    
    def _bld_deps(self) -> Dict[str, Dict]:
        """
        Build zone dependency graph by scanning key:/ directory.
        
        Returns:
            Dictionary mapping zone_name to {
                'service': service_name,
                'parent': parent_zone_name,
                'children': [child_zone_names],
                'temp_path_prefix': temp path prefix
            }
        """
        graph = {}
        key_root = DNSBPath("key:/")
        
        if not self.fs.exists(key_root):
            logger.warning("[DNSSEC-Resigner] key:/ path does not exist")
            return graph
        
        # Find all .ksk.key files to identify zones
        ksk_files = self.fs.rglob(key_root, "*ksk.key")
        logger.debug(f"[DNSSEC-Resigner] Found {len(ksk_files)} KSK key file(s)")
        
        for ksk_path in ksk_files:
            try:
                # Parse path: key:/service/zone.ksk.key
                
                service_name = ksk_path.parent.name
                zone_filename = ksk_path.name
                zone_name_clean = zone_filename.replace('.ksk.key', '')
                
                # Handle special root zone naming
                if zone_name_clean == 'root' or zone_name_clean == '':
                    zone_name = '.'
                else:
                    zone_name = zone_name_clean + '.'
                
                # Determine parent zone
                parent_zone = self._find_parent(zone_name)
                
                # Add to graph
                if zone_name not in graph:
                    graph[zone_name] = {
                        'service': service_name,
                        'parent': parent_zone,
                        'children': [],
                        'temp_path_prefix': f"temp:/services/{service_name}/zones/",
                        'zone_name_clean': zone_name_clean
                    }
                
                logger.debug(f"[DNSSEC-Resigner] Added zone '{zone_name}' (service: {service_name}, parent: {parent_zone})")
                
            except Exception as e:
                logger.warning(f"[DNSSEC-Resigner] Failed to parse {ksk_path}: {e}")
        
        # Build children relationships
        for zone_name, zone_info in graph.items():
            parent = zone_info['parent']
            if parent and parent in graph:
                graph[parent]['children'].append(zone_name)
        
        return graph
    
    def _find_parent(self, zone_name: str) -> Optional[str]:
        """
        Determine the parent zone for a given zone name.
        
        Args:
            zone_name: Zone name (e.g., 'com.', 'example.com.', '.')
            
        Returns:
            Parent zone name or None if no parent (root zone)
        """
        if zone_name == '.':
            return None  # Root has no parent
        
        zone_clean = zone_name.rstrip('.')
        parts = zone_clean.split('.')
        
        if len(parts) == 1:
            return '.'  # TLD's parent is root
        
        # Parent is everything after the first label
        return '.'.join(parts[1:]) + '.'
    
    def _topological_sort(self, graph: Dict[str, Dict]) -> List[str]:
        """
        Sort zones in topological order
        ensures child zones are processed before their parents,
        """
        # Use depth-first search to order zones
        visited = set()
        result = []
        
        def visit(zone: str):
            if zone in visited:
                return
            visited.add(zone)
            
            # Visit children first
            zone_info = graph.get(zone)
            if zone_info:
                for child in zone_info['children']:
                    if child in graph:
                        visit(child)
            
            # Then add parent
            result.append(zone)
        
        # Start from all zones
        for zone in graph.keys():
            visit(zone)
        
        return result
    
    def _resign_parent_zone(self, parent_zone: str, zone_graph: Dict[str, Dict]) -> bool:
        """
        Re-sign a parent zone with DS records from its children.
        
        Args:
            parent_zone: Parent zone name to re-sign
            zone_graph: Complete zone dependency graph
            
        Returns:
            True if re-signing succeeded, False otherwise
        """
        try:
            zone_info = zone_graph[parent_zone]
            service_name = zone_info['service']
            zone_name_clean = zone_info['zone_name_clean']
            children = zone_info['children']
            
            # Read unsigned zone content from temp:/
            base_filename = f"db.{zone_name_clean}" if parent_zone != "." else "db.root"
            unsigned_path = DNSBPath(f"{zone_info['temp_path_prefix']}{base_filename}.unsigned")
            
            if not self.fs.exists(unsigned_path):
                logger.error(f"[DNSSEC-Resigner] Unsigned zone file not found: {unsigned_path}")
                return False
            
            unsigned_content = self.fs.read_text(unsigned_path)
            logger.debug(f"[DNSSEC-Resigner] Read unsigned zone from {unsigned_path}")
            
            # Collect DS records from all children
            ds_records_content = []
            
            for child_zone in children:
                if child_zone not in zone_graph:
                    logger.warning(f"[DNSSEC-Resigner] Child zone '{child_zone}' not in graph")
                    continue
                
                child_info = zone_graph[child_zone]
                child_service = child_info['service']
                child_zone_clean = child_info['zone_name_clean']
                
                # Read DS record from key:/
                ds_path = DNSBPath(f"key:/{child_service}/{child_zone_clean}.ds")
                
                if not self.fs.exists(ds_path):
                    logger.warning(f"[DNSSEC-Resigner] DS record not found for child '{child_zone}': {ds_path}")
                    continue
                
                ds_content = self.fs.read_text(ds_path)
                if ds_content.strip():
                    ds_records_content.append(f"; DS records for {child_zone}")
                    ds_records_content.append(ds_content.strip())
                    logger.debug(f"[DNSSEC-Resigner] Collected DS records for '{child_zone}'")
            
            if not ds_records_content:
                logger.warning(f"[DNSSEC-Resigner] No DS records found for children of '{parent_zone}'")
                return False
            
            # Append DS records to unsigned zone content
            modified_content = unsigned_content + "\n\n" + "\n".join(ds_records_content) + "\n"
            
            # Re-sign the zone with modified content
            signed_result = self._resign_zone(
                parent_zone,
                zone_name_clean,
                service_name,
                modified_content
            )
            
            if not signed_result:
                logger.error(f"[DNSSEC-Resigner] Failed to sign '{parent_zone}'")
                return False
            
            signed_content, new_ds_content = signed_result
            
            # Update temp:/ with new signed zone
            signed_path = DNSBPath(f"{zone_info['temp_path_prefix']}{base_filename}")
            self.fs.write_text(signed_path, signed_content)
            logger.debug(f"[DNSSEC-Resigner] Updated signed zone at {signed_path}")
            
            # Update key:/ with new DS record (for use by parent zones)
            if new_ds_content:
                ds_output_path = DNSBPath(f"key:/{service_name}/{zone_name_clean}.ds")
                self.fs.write_text(ds_output_path, new_ds_content)
                logger.debug(f"[DNSSEC-Resigner] Updated DS record at {ds_output_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"[DNSSEC-Resigner] Exception while re-signing '{parent_zone}': {e}")
            logger.exception(e)
            return False
    
    def _resign_zone(
        self,
        zone_name: str,
        zone_name_clean: str,
        service_name: str,
        unsigned_content: str
    ) -> Optional[Tuple[str, str]]:
        """
        Sign a zone using existing keys from key:/.
        
        Args:
            zone_name: Zone name (e.g., 'com.', '.')
            zone_name_clean: Clean zone name (e.g., 'com', 'root')
            service_name: Service name managing this zone
            unsigned_content: Unsigned zone file content (with DS records appended)
            
        Returns:
            Tuple of (signed_content, ds_content) or None on failure
        """
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # Write unsigned zone content
                zone_filename = f"db.{zone_name_clean}" if zone_name != "." else "db.root"
                unsigned_file = temp_path / zone_filename
                unsigned_file.write_text(unsigned_content)
                
                # Read existing keys from key:/
                ksk_key_path = DNSBPath(f"key:/{service_name}/{zone_name_clean}.ksk.key")
                ksk_private_path = DNSBPath(f"key:/{service_name}/{zone_name_clean}.ksk.private")
                zsk_key_path = DNSBPath(f"key:/{service_name}/{zone_name_clean}.zsk.key")
                zsk_private_path = DNSBPath(f"key:/{service_name}/{zone_name_clean}.zsk.private")
                keynames_path = DNSBPath(f"key:/{service_name}/{zone_name_clean}.keynames")
                
                # Check all key files exist
                for key_path in [ksk_key_path, ksk_private_path, zsk_key_path, zsk_private_path, keynames_path]:
                    if not self.fs.exists(key_path):
                        logger.error(f"[DNSSEC-Resigner] Key file not found: {key_path}")
                        return None
                
                # Read key basenames from metadata file
                # Format: KSK_BASENAME=K.+013+61193\nZSK_BASENAME=K.+013+14828
                keynames_content = self.fs.read_text(keynames_path)
                ksk_basename = None
                zsk_basename = None
                for line in keynames_content.strip().split('\n'):
                    if line.startswith('KSK_BASENAME='):
                        ksk_basename = line.split('=', 1)[1]
                    elif line.startswith('ZSK_BASENAME='):
                        zsk_basename = line.split('=', 1)[1]
                
                if not ksk_basename or not zsk_basename:
                    logger.error(f"[DNSSEC-Resigner] Failed to parse key basenames from {keynames_path}")
                    logger.error(f"[DNSSEC-Resigner] Content: {keynames_content}")
                    return None
                
                logger.debug(f"[DNSSEC-Resigner] Using KSK basename: {ksk_basename}, ZSK basename: {zsk_basename}")
                
                # Read key contents
                ksk_key_content = self.fs.read_text(ksk_key_path)
                ksk_private_content = self.fs.read_text(ksk_private_path)
                zsk_key_content = self.fs.read_text(zsk_key_path)
                zsk_private_content = self.fs.read_text(zsk_private_path)
                
                # Write key files to temp directory with BIND standard names
                (temp_path / f"{ksk_basename}.key").write_text(ksk_key_content)
                (temp_path / f"{ksk_basename}.private").write_text(ksk_private_content)
                (temp_path / f"{zsk_basename}.key").write_text(zsk_key_content)
                (temp_path / f"{zsk_basename}.private").write_text(zsk_private_content)
                
                # Append key includes to zone file
                unsigned_file.write_text(
                    unsigned_file.read_text() + "\n" +
                    f"$INCLUDE {ksk_basename}.key\n" +
                    f"$INCLUDE {zsk_basename}.key\n"
                )
                
                # Sign the zone
                logger.debug(f"[DNSSEC-Resigner] Signing zone '{zone_name}' with dnssec-signzone")
                sign_result = subprocess.run(
                    [
                        "dnssec-signzone",
                        "-3", hashlib.sha1(zone_name.encode()).hexdigest()[:16],
                        "-N", "INCREMENT",
                        "-o", zone_name,
                        str(unsigned_file)
                    ],
                    cwd=temp_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                
                logger.debug(f"[DNSSEC-Resigner] dnssec-signzone output: {sign_result.stdout}")
                
                # Read signed zone
                signed_file = temp_path / f"{zone_filename}.signed"
                if not signed_file.exists():
                    logger.error(f"[DNSSEC-Resigner] Signed zone file not found: {signed_file}")
                    return None
                
                signed_content = signed_file.read_text()
                
                # Read DS records
                dsset_file = temp_path / f"dsset-{zone_name_clean}."
                ds_content = ""
                if dsset_file.exists():
                    ds_content = dsset_file.read_text()
                    logger.debug(f"[DNSSEC-Resigner] Found new DS records for '{zone_name}'")
                else:
                    logger.warning(f"[DNSSEC-Resigner] DS record file not found: {dsset_file}")
                
                return (signed_content, ds_content)
                
        except subprocess.CalledProcessError as e:
            logger.error(f"[DNSSEC-Resigner] dnssec-signzone failed for '{zone_name}': {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"[DNSSEC-Resigner] Failed to sign zone '{zone_name}': {e}")
            logger.exception(e)
            return None


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
            resigner = DNSSECResigner(self.context)
            resigner.run()
            
            # Generate root.key trust anchor for recursive resolvers
            self._generate_root_key()
            
            # Combine all DS records for documentation
            self._combine_ds_records()
            
            logger.info("[DNSSEC] DNSSEC key processing completed successfully.")
        except Exception as e:
            logger.error(f"[DNSSEC] Error during DNSSEC processing: {e}")
            # Log the error but don't raise to avoid breaking the barrier
            # Services can continue even if DNSSEC processing fails
    
    def _generate_root_key(self) -> None:
        """
        Generate root.key trust anchor file from all KSK keys.
        
        This method scans the key:/ protocol path for all *.ksk.key files,
        """
        logger.debug("[DNSSEC] Generating root.key trust anchor...")
        
        # Find all KSK key files under key:/
        ksk_files = self._find_root()
        
        if not ksk_files:
            logger.warning("[DNSSEC] No KSK key files found in key:/. Skipping root.key generation.")
            return
        
        logger.info(f"[DNSSEC] Found {len(ksk_files)} KSK key file(s) for root.key")
        
        # Read and combine all KSK key contents
        combined_content = []
        for ksk_file in ksk_files:
            try:
                content = self.fs.read_text(ksk_file)
                if content.strip():  # Only add non-empty content
                    combined_content.append(content.strip())
                    logger.debug(f"[DNSSEC] Added KSK from {ksk_file}")
            except Exception as e:
                logger.warning(f"[DNSSEC] Failed to read {ksk_file}: {e}")
        
        if not combined_content:
            logger.warning("[DNSSEC] All KSK key files were empty or unreadable.")
            return
        
        # Write combined content to key:/root.key
        output_path = DNSBPath("key:/root.key")
        combined_text = "\n\n".join(combined_content) + "\n"
        
        try:
            self.fs.write_text(output_path, combined_text)
            logger.info(f"[DNSSEC] Successfully generated {output_path} with {len(combined_content)} KSK key(s)")
            logger.info(f"[DNSSEC] root.key can be used as trust-anchor-file for recursive resolvers")
            logger.debug(f"[DNSSEC] root.key file size: {len(combined_text)} bytes")
        except Exception as e:
            logger.error(f"[DNSSEC] Failed to write root.key to {output_path}: {e}")
    
    def _find_root(self) -> List[DNSBPath]:
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
            
            # find the root
            ksk_files = self.fs.rglob(key_root, ".ksk.key")
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