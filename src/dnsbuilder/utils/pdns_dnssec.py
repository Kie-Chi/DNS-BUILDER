"""PowerDNS BIND-backend DNSSEC metadata generation.

PowerDNS does not infer the presigned NSEC/NSEC3 mode from the zone file
alone.  The builder writes the small BIND DNSSEC SQLite database directly so
the build does not need to install or invoke ``pdnsutil``.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Mapping

from ..exceptions import BuildError


class PdnsDnssecMetadataError(BuildError):
    """Raised when a signed zone cannot produce valid PowerDNS metadata."""


_NSEC3PARAM_RE = re.compile(
    r"\bNSEC3PARAM\s+(?P<algorithm>\d+)\s+(?P<flags>\d+)\s+"
    r"(?P<iterations>\d+)\s+(?P<salt>[0-9A-Fa-f-]+)",
    re.IGNORECASE,
)

_SCHEMA = (
    "CREATE TABLE cryptokeys ("
    "id INTEGER PRIMARY KEY, domain VARCHAR(255) COLLATE NOCASE, "
    "flags INT NOT NULL, active BOOL, published BOOL DEFAULT 1, content TEXT)",
    "CREATE TABLE domainmetadata ("
    "id INTEGER PRIMARY KEY, domain VARCHAR(255) COLLATE NOCASE, "
    "kind VARCHAR(32) COLLATE NOCASE, content TEXT)",
    "CREATE TABLE tsigkeys ("
    "id INTEGER PRIMARY KEY, name VARCHAR(255) COLLATE NOCASE, "
    "algorithm VARCHAR(50) COLLATE NOCASE, secret VARCHAR(255))",
    "CREATE INDEX domainmetanameindex ON domainmetadata(domain)",
    "CREATE INDEX domainnameindex ON cryptokeys(domain)",
    "CREATE UNIQUE INDEX namealgoindex ON tsigkeys(name, algorithm)",
)


def _metadata_for_zone(zone: str, content: str) -> str:
    matches = list(_NSEC3PARAM_RE.finditer(content))
    if not matches:
        raise PdnsDnssecMetadataError(
            f"Signed zone {zone!r} does not contain an NSEC3PARAM record"
        )
    values = {
        (
            match.group("algorithm"),
            match.group("flags"),
            match.group("iterations"),
            match.group("salt").lower(),
        )
        for match in matches
    }
    if len(values) != 1:
        raise PdnsDnssecMetadataError(
            f"Signed zone {zone!r} contains conflicting NSEC3PARAM values: {sorted(values)!r}"
        )
    algorithm, flags, iterations, salt = next(iter(values))
    if algorithm != "1":
        raise PdnsDnssecMetadataError(
            f"Signed zone {zone!r} uses unsupported NSEC3 hash algorithm {algorithm!r}"
        )
    return f"{algorithm} {flags} {iterations} {salt}"


def write_bind_dnssec_db(zone_contents: Mapping[str, str], destination: Path) -> Path:
    """Create a complete BIND DNSSEC SQLite DB for presigned zones.

    ``zone_contents`` maps zone names to their final signed zone file text.
    The database is replaced as one build artifact and contains only metadata;
    PowerDNS will read the signed RRSIG/DNSKEY records from the zone files.
    """
    if not zone_contents:
        raise PdnsDnssecMetadataError("Cannot create a DNSSEC metadata DB without zones")

    metadata = []
    seen_zones = set()
    for zone, content in zone_contents.items():
        canonical_zone = zone.rstrip(".").lower() or "."
        if canonical_zone in seen_zones:
            raise PdnsDnssecMetadataError(
                f"Duplicate PowerDNS metadata zone after canonicalization: {zone!r}"
            )
        seen_zones.add(canonical_zone)
        metadata.append((canonical_zone, "PRESIGNED", "1"))
        metadata.append((canonical_zone, "NSEC3PARAM", _metadata_for_zone(zone, content)))

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    connection = sqlite3.connect(destination)
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        connection.executemany(
            "INSERT INTO domainmetadata(domain, kind, content) VALUES (?, ?, ?)",
            metadata,
        )
        connection.commit()
        rows = connection.execute(
            "SELECT domain, kind, content FROM domainmetadata ORDER BY domain, kind"
        ).fetchall()
        if len(rows) != len(metadata):
            raise PdnsDnssecMetadataError(
                f"PowerDNS metadata verification failed for {destination}"
            )
    finally:
        connection.close()
    return destination
