#!/usr/bin/env python3
"""Bounded DNSSEC query probe for the KeyTrap reproduction."""
import json, os, socket, struct, sys, time

def qname(name):
    return b"".join(bytes([len(x)]) + x.encode() for x in name.rstrip(".").split(".")) + b"\0"

def main():
    resolver = os.environ.get("R", "resolver")
    name = os.environ.get("DNSB_QUERY_NAME", "www.example.com.")
    # EDNS(0) OPT with DO=1: root owner, type 41, payload 4096, TTL DO bit,
    # and an empty option section.
    query = struct.pack("!HHHHHH", 0x5154, 0x0100, 1, 0, 0, 1) + qname(name) + struct.pack("!HH", 1, 1) + b"\0" + struct.pack("!HHIH", 41, 4096, 0x00008000, 0)
    started = time.perf_counter()
    metric = {"server": resolver, "name": name, "query_bytes": len(query), "timeout": False, "rcode": None, "answer_count": None, "authority_count": None, "additional_count": None}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(float(os.environ.get("DNSB_QUERY_TIMEOUT", "8")))
            sock.sendto(query, (resolver, 53)); response, _ = sock.recvfrom(65535)
        if len(response) < 12: raise ValueError("short DNS response")
        _ident, flags, _qd, an, ns, ar = struct.unpack("!HHHHHH", response[:12])
        metric.update({"response_bytes": len(response), "rcode": flags & 15, "answer_count": an, "authority_count": ns, "additional_count": ar})
    except socket.timeout:
        metric.update({"timeout": True, "response_bytes": 0})
    except Exception as exc:
        metric["error"] = f"{type(exc).__name__}: {exc}"
    metric["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    print(json.dumps(metric, sort_keys=True), flush=True)
    return 0 if metric.get("timeout") or metric.get("rcode") not in (None, 0) else 1

if __name__ == "__main__": sys.exit(main())
