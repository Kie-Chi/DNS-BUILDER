# DART: DNS Attack Reproduction and Testing Framework

DART is a comprehensive DNS testing framework built on top of [DNS-BUILDER](depends/DNS-BUILDER/README.md). It enables researchers to rapidly construct, reproduce, and evaluate DNS attack scenarios, measure resolver behavior, and validate DNS protocol compliance—all within isolated, containerized environments.

## Project Structure

```
dart/
├── app/          # Application-layer evaluation
├── bugs/         # DNS attack reproduction test suites
├── depends/      # Dependency tools (DNS-SAK, DNS-BUILDER, DNS-FUZZER, DNS-Monitor)
```

## Key Components

- **bugs/** — Reproduction configurations for 21 known DNS attacks (e.g., Kaminsky, KeyTrap, TsuKing, CAMP, DNSBomb, NRDelegation, NXNS, TsuName, etc.), each defined as a DNS-BUILDER YAML config that spawns the full attack topology.
- **app/** — Application-layer evaluations: cache behavior analysis, RFC-compliance difference detection, and error-handling testing using DNS-FUZZER and DNS-Monitor.
- **depends/** — Core tool dependencies: DNS-BUILDER (environment orchestration), DNS-FUZZER (protocol fuzzing & analysis), and DNS-Monitor (real-time DNS traffic observability).

## Requirements

- Python >= 3.12
- Docker
- DNS-BUILDER (`pip install depends/DNS-BUILDER`)

## License

Not Yet