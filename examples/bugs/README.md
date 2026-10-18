# DNS Attack Reproduction Test Suites

This directory contains DNS-BUILDER configuration files for reproducing 21 known DNS attacks and vulnerabilities. Each subdirectory defines a complete attack topology — including victim resolvers, authoritative servers, attacker nodes, and network topology — that can be built and run with a single `dnsb run` command.

## Attack Scenarios

| Directory | Attack | Description |
|-----------|--------|-------------|
| `badcache` | BadCache | Exploits improper caching of poisoned records by resolvers |
| `birthdays` | Birthday Attack | DNS cache poisoning leveraging birthday paradox probability |
| `camp` | CAMP | Composite DNS amplification attack with multi-stage chaining (CN-QM, DD-FO, FO-CN, NS-FO variants) |
| `cuckoo` | Cuckoo | DNSSEC Baliwick cache poisoning attack targeting BIND, Unbound, Knot, and PowerDNS |
| `disbalance` | Disbalance | Load imbalance exploitation in DNS Resolver |
| `dnsbomb` | DNSBomb | DNS amplification bomb exploiting EDNS0 and resolver timeout windows |
| `dnspun` | DNS Pun | DNS deauthentication attack using crafted responses |
| `downgraddnssec` | DNSSEC Downgrade | Forces downgrade from DNSSEC-validated to unsigned resolution |
| `fragforward` | Fragment Forwarding | IP fragmentation-based DNS poisoning through forwarders |
| `inject` | DNS Injection | DNS response injection cache poisoning reloaded |
| `kaminsky` | Kaminsky Attack | Classic DNS cache poisoning with forged authoritative responses |
| `keytrap` | KeyTrap | DNSSEC key rollover exploitation causing resolver CPU exhaustion |
| `loopy` | Loopy | DNS Application Layer resolution loop causing infinite referral chains |
| `maginot` | Maginot | DNS Baliwick cache poisoning through forwarded resolution manipulation |
| `phoenix` | Phoenix (Ghost) | Phantom DNS record persistence after TTL expiration |
| `tsuking` | TsuKing | Multi-level DNS amplification chain attack |
| `nrdelegation` | NRDelegation (NRDG) | Name Referral Delegation amplification attack using massive non-existent NS records |
| `nxns` | NXNS | NXNS amplification attack exploiting non-existent domain NS referrals |
| `tsuname` | TsuName | DNS resolution loop attack via CNAME/NS circular references causing infinite referral chains |
| `tudoor` | TuDoor | DNS tunnel door attack through delegation manipulation |

## Directory Structure

Each attack subdirectory typically contains:

- `main.yml` — Primary DNS-BUILDER configuration defining the attack topology
- `resource/` — Attack-specific resources (server scripts, configuration templates, Dockerfiles)
- `share/` — Shared configuration fragments reusable across scenarios
- `conf/` — Additional resolver/server configuration files
- `output/` — Generated Docker Compose output (created by `dnsb build`)
- `img/` — Docker images 

## How to Run

To reproduce any attack scenario:

```bash
# From the specific attack directory
dnsb run main.yml

# Or build first, then run manually
dnsb build main.yml
cd output/<name>
docker compose up -d
```

For multi-variant attacks (e.g., CAMP with 4 chain combinations), each variant has its own configuration:

```bash
# CAMP variants
dnsb run camp-cn-qm.yml   # CN x QM chain
dnsb run camp-dd-fo.yml   # DD x FO chain
dnsb run camp-fo-cn.yml   # FO x CN chain
dnsb run camp-ns-fo.yml   # NS x FO chain

# TsuName variants
dnsb run main-ns.yml      # NS-based circular referral
dnsb run main-cname.yml   # CNAME-based circular referral
```

## LoC Calculator

`calc.py` provides a Lines of Code (LoC) calculator that counts configuration LoC in the generated Docker Compose output, useful for efficiency comparison experiments.
