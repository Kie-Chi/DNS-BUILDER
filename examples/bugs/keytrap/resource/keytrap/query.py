#!/usr/bin/env python3
"""Trigger the KeyTrap resolver path with a DNS query.

The sld hook in main.yml injects the crafted RRSIG records at
``www.example.com.``.  The resolver address is supplied by DNSB through the
R environment variable.
"""

import os
import random
import socket
import struct
import sys


QTYPE = {
    "A": 1,
    "AAAA": 28,
    "DNSKEY": 48,
}


def encode_qname(name: str) -> bytes:
    """Encode a DNS name into DNS label format."""
    name = name.rstrip(".")
    if not name:
        return b"\x00"
    return b"".join(
        bytes([len(label)]) + label.encode("idna")
        for label in name.split(".")
    ) + b"\x00"


def make_query(name: str, query_type: str) -> tuple[int, bytes]:
    """Build an A/AAAA/DNSKEY query with the DNSSEC OK (DO) bit."""
    qtype = QTYPE.get(query_type.upper())
    if qtype is None:
        raise ValueError(f"Unsupported query type: {query_type}")

    query_id = random.randrange(0, 65536)
    # RD=1, one question, and one EDNS(0) OPT record requesting DNSSEC data.
    header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 1)
    question = encode_qname(name) + struct.pack("!HH", qtype, 1)
    # OPT: root owner, TYPE=41, UDP payload=4096, DO=1, no options.
    opt = b"\x00" + struct.pack("!HHIH", 41, 4096, 0x00008000, 0)
    return query_id, header + question + opt


def main() -> int:
    resolver = os.environ.get("R", "10.10.0.6")
    query_name = os.environ.get("DNSB_QUERY_NAME", "www.example.com.")
    query_type = os.environ.get("DNSB_QUERY_TYPE", "A")
    query_port = int(os.environ.get("DNSB_QUERY_PORT", "53"))
    timeout = float(os.environ.get("DNSB_QUERY_TIMEOUT", "10"))

    print(
        f"Querying {query_name} {query_type} via {resolver}:{query_port}",
        flush=True,
    )

    try:
        query_id, request = make_query(query_name, query_type)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(request, (resolver, query_port))
            response, _ = sock.recvfrom(65535)

        if len(response) < 12:
            raise ValueError("DNS response is shorter than the DNS header")
        response_id, flags, questions, answers, authority, additional = struct.unpack(
            "!HHHHHH", response[:12]
        )
        if response_id != query_id:
            raise ValueError("DNS response ID does not match the query")
    except Exception as exc:
        print(f"DNS query failed: {exc}", file=sys.stderr, flush=True)
        return 1

    print(
        f"rcode={flags & 0x000F} answers={answers} "
        f"authority={authority} additional={additional} "
        f"questions={questions}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
