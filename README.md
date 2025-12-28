# DNS-BUILDER

A tool to generate complex DNS test environments using Docker.

## Quick Start

### Installation

```bash
pip install .
```

### Usage

```bash
dnsb build config.yml
# Or to run directly after building
dnsb run config.yml
```

## Features

- Rapidly build complex DNS test environments
- Docker-based containerized deployment
- DNSSEC configuration support
- Flexible configuration file format, even using Python scripts
- Automated zone file generation and management, greatly supporting Bind9/Unbound/Knot-resolver/PowerDNS-recursor

## Documentation

Detailed documentation is available in the `doc/` directory:

- [Getting Started](doc/root/getting-started.md)
- [Installation Guide](doc/root/install.md)
- [Configuration](doc/config/index.md)
- [Rule System](doc/rule/index.md)
- [API Documentation](doc/api/index.md)
- [FAQ](doc/faq.md)

or visit [web docs](https://kie-chi.github.io/DNS-BUILDER/).

## Project Structure

```
├── src/dnsbuilder/    # Source code
├── doc/               # Documentation
├── test/              # Test files
├── output/            # Build output
└── scripts/           # Helper scripts
```

## Requirements

- Python >= 3.12
- Docker

## License

Not Yet