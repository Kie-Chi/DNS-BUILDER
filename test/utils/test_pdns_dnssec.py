import sqlite3

import pytest

from dnsbuilder.utils.pdns_dnssec import (
    PdnsDnssecMetadataError,
    write_bind_dnssec_db,
)


def test_write_bind_dnssec_db_creates_powerdns_schema(tmp_path):
    destination = tmp_path / "metadata" / "bind-dnssec-db.sqlite3"
    write_bind_dnssec_db(
        {"cn.": "@ 3600 IN NSEC3PARAM 1 0 0 B0BC9ABD90E2F7B3\n"},
        destination,
    )

    connection = sqlite3.connect(destination)
    try:
        rows = connection.execute(
            "SELECT domain, kind, content FROM domainmetadata ORDER BY kind"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        ("cn", "NSEC3PARAM", "1 0 0 b0bc9abd90e2f7b3"),
        ("cn", "PRESIGNED", "1"),
    ]


def test_write_bind_dnssec_db_rejects_missing_nsec3param(tmp_path):
    with pytest.raises(PdnsDnssecMetadataError, match="NSEC3PARAM"):
        write_bind_dnssec_db({"cn": "@ 3600 IN SOA ns host 1 2 3 4 5\n"}, tmp_path / "db.sqlite3")
