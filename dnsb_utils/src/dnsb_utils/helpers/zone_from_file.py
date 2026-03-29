"""
zone_from_file helper function

Parses zone files and converts to behavior configuration lines.
Uses dnslib's ZoneParser for robust, native parsing of both 
standard BIND formats and simplified formats.
"""

import logging
import inspect
from typing import Optional, List

from dnslib import QTYPE, ZoneParser

try:
    from dnsbuilder import Zone, constants
except ImportError:
    # Fallback for standalone usage
    Zone = None
    constants = None

logger = logging.getLogger(__name__)

# Record types we support (QTYPE integers, not RData classes)
SUPPORTED_TYPES = {QTYPE.A, QTYPE.AAAA, QTYPE.NS, QTYPE.CNAME,
                   QTYPE.MX, QTYPE.TXT, QTYPE.PTR, QTYPE.SRV}


def zone_from_file(file_path: str, zone_name: Optional[str] = None) -> None:
    """
    Read a zone file and convert to behavior config lines.

    Supports two formats via dnslib's native ZoneParser:
    1. BIND zone file format (with $ORIGIN, $TTL directives)
    2. Simplified record format: <name> <type> [<ttl>] <value>

    Args:
        file_path: Path to zone file (relative to workdir or absolute)
        zone_name: Zone name for records. Required for simplified format.
                   For BIND format, extracted from $ORIGIN if not provided.

    Note:
        This function uses global variables injected by ScriptExecutor:
        - fs: FileSystem for reading files
        - config: Configuration dictionary (will add behaviors to config['behaviors'])
    """
    # Get caller's globals (injected by ScriptExecutor)
    frame = inspect.currentframe()
    if frame and frame.f_back:
        caller_globals = frame.f_back.f_globals
        fs = caller_globals.get('fs')
        config = caller_globals.get('config')
    else:
        fs = None
        config = None

    if fs is None:
        raise RuntimeError(
            "FileSystem not available. "
            "zone_from_file must be called from an auto script context."
        )

    if config is None:
        raise RuntimeError(
            "Config not available. "
            "zone_from_file must be called from an auto script context."
        )

    # Read file content
    from dnsbuilder.io import DNSBPath
    content = fs.read_text(DNSBPath(file_path))

    # Parse and add behaviors to config
    # behavior is a multiline string, not a list
    behavior_str = config.get("behavior", "")
    logger.debug(f"[zone_from_file] Zonefile: {content}")
    new_lines = _parse_zone_content(content, zone_name)
    logger.debug(f"[zone_from_file] Parsed {len(new_lines)} behavior lines")
    logger.debug(f"[zone_from_file] new_lines: {new_lines}")
    if behavior_str:
        config["behavior"] = behavior_str + "\n" + "\n".join(new_lines)
    else:
        config["behavior"] = "\n".join(new_lines)
    logger.debug(f"[zone_from_file] config['behavior'] after update: {repr(config.get('behavior'))}")


def _parse_zone_content(content: str, zone_name: Optional[str] = None) -> List[str]:
    behavior_lines = []
    origin_str = None
    if zone_name:
        origin_str = f"{zone_name.rstrip('.') }."
    else:
        for line in content.splitlines():
            if line.upper().strip().startswith('$ORIGIN'):
                parts = line.split()
                if len(parts) > 1:
                    origin_str = parts[1]
                    if not origin_str.endswith('.'):
                        origin_str += '.'
                break
                
    if not origin_str:
        raise ValueError("zone_name is required if $ORIGIN is not present in the file.")
        
    zone_label = origin_str.rstrip('.')
    processed_lines = []
    if "$TTL" not in content.upper():
        processed_lines.append("$TTL 3600")
        
    for line in content.splitlines():
        if line.upper().strip().startswith('$INCLUDE'):
            logger.warning(f"$INCLUDE directive not supported in zone_from_file: {line}")
            continue
        processed_lines.append(line)

    try:
        parser = ZoneParser('\n'.join(processed_lines), origin=origin_str)
        records = list(parser)
        logger.debug(f"[zone_from_file] ZoneParser parsed {len(records)} records")
    except Exception as e:
        logger.error(f"ZoneParser failed to parse content: {e}")
        logger.debug(f"[zone_from_file] Processed content:\n{repr('\n'.join(processed_lines))}")
        return []
    for rr in records:
        if rr.rtype not in SUPPORTED_TYPES or rr.rtype == QTYPE.SOA:
            continue
            
        rtype_str = QTYPE.get(rr.rtype, str(rr.rtype))
        rdata_str = rr.rdata.toZone()
        rr_name = str(rr.rname)
        if rr_name == origin_str:
            rel_name = '@'
        elif rr_name.endswith("." + origin_str):
            rel_name = rr_name[:-(len(origin_str) + 1)]
        else:
            rel_name = rr_name.rstrip('.')
        behavior_lines.append(
            f"{zone_label} master {rel_name} {rtype_str} {rr.ttl} {rdata_str}"
        )

    return behavior_lines