from enum import Enum
from dnslib import A, CNAME, AAAA, TXT, NS

# --- Log and Debug ---
# Short aliases for module names to keep CLI/env concise
LOG_ALIAS_MAP = {
    "sub": "dnsbuilder.builder.substitute",
    "resolve": "dnsbuilder.builder.resolve",
    "rlv": "dnsbuilder.builder.resolve",
    "rsv": "dnsbuilder.builder.resolve",
    "res": "dnsbuilder.builder.resolve",
    "build": "dnsbuilder.builder.build",
    "bld": "dnsbuilder.builder.build",
    "service": "dnsbuilder.builder.service",
    "srv": "dnsbuilder.builder.service",
    "svc": "dnsbuilder.builder.service",
    "net": "dnsbuilder.builder.net",
    "map": "dnsbuilder.builder.map",
    "io": "dnsbuilder.io",
    "fs": "dnsbuilder.io.fs",
    "conf": "dnsbuilder.config",
    "api": "dnsbuilder.api",
    "pre": "dnsbuilder.preprocess",
    "cbld": "dnsbuilder.builder.cached_builder",
    "cache": "dnsbuilder.cache",
    "cc": "dnsbuilder.cache",
    "rty": "dnsbuilder.registry",
    "auto": "dnsbuilder.auto",
}

# Top-level modules within dnsbuilder for auto-prefixing
KNOWN_TOP_MODULES = {
    "builder",
    "io",
    "api",
    "resources",
    "rules",
    "bases",
    "datacls",
    "utils",
    "exceptions",
    "config",
    "cache",
    "registry",
    "auto",
}


# --- Filenames and Paths ---
GENERATED_ZONES_FILENAME = "generated_zones.conf"
GENERATED_ZONES_SUBDIR = "zones"
INCLUDE_SUBDIR = "includes"
DOCKERFILE_NAME = "Dockerfile"
DOCKER_COMPOSE_FILENAME = "docker-compose.yml"

# --- Prefixes ---
RESOURCE_PREFIX = "resource:"
STD_BUILD_PREFIX = "std:"

# DNS Software Top-level Block Definitions
DNS_SOFTWARE_BLOCKS = {
    "bind": {
        "global",
        "acl",          # Access Control Lists
        "controls",     # Control channel configuration
        "options",      # Global options
        "logging",      # Logging configuration
        "zone",         # Zone definitions
        "view",         # View definitions
        "key",          # TSIG key definitions
        "server",       # Server-specific options
        "trusted-keys", # Trusted keys for DNSSEC
        "managed-keys", # Managed keys for DNSSEC
        "statistics-channels", # Statistics channel configuration
    },
    "unbound": {
        "global",
        "server",           # Main server configuration
        "remote-control",   # Remote control configuration
        "stub-zone",        # Stub zone configuration
        "forward-zone",     # Forward zone configuration
        "auth-zone",        # Authoritative zone configuration
        "view",             # View configuration
        "python",           # Python module configuration
        "dynlib",           # Dynamic library configuration
    },
    "pdns_recursor": {
        "global",           # PowerDNS Recursor only has global configuration
    }
}

RECOGNIZED_PATTERNS = {
    "bind": [
        r"\bbind(?![a-zA-Z])",  # exact word match
        r"\bisc-bind(?![a-zA-Z])",  # ISC BIND
        r"\bnamed(?![a-zA-Z])",  # BIND daemon name
    ],
    "unbound": [
        r"\bunbound(?![a-zA-Z])"  # exact word match
    ],
    "pdns_recursor": [
        r"\bpdns[_-]?recursor(?![a-zA-Z])",  # pdns_recursor or pdns-recursor
        r"\bpowerdns[_-]?recursor(?![a-zA-Z])",  # powerdns_recursor or powerdns-recursor
    ],
}


# --- Behavior Sections ---

BEHAVIOR_TYPES = {"Forward", "Stub", "Master", "Hint", "Slave"}

class BehaviorSection(str, Enum):
    SERVER = "server"
    TOPLEVEL = "toplevel"

RECORD_TYPE_MAP = {
    "A": A,
    "NS": NS,
    "AAAA": AAAA,
    "CNAME": CNAME,
    "TXT": TXT,
}

# --- Place Holder ---
PLACEHOLDER = {
    "REQUIRED": "${required}",
    "ORIGIN": "${origin}",
    # add more place holders, avoiding replaced by VariableSubstituter
}

# --- Alias Variable ---
ALIAS_MAP = {
    "address": "ip",
    "s": "services",
    "img": "image",
    "svc": "services",
    "srv": "services",
    "addr": "ip",
    "network": "inet",
    "proj": "project",
    "reference": "ref",
    "caps": "cap_add",
    "cap": "cap_add",
    "vols": "volumes",
    "stack": "software",
    "env": "environment",
    "ver": "version",
}

# --- supported protocol ---
KNOWN_PROTOCOLS = {"http", "https", "ftp", "s3", "gs", "file", "resource", "temp", "git", "cache"}

# --- Docker Compose Keys & Values ---
DEFAULT_CAP_ADD = ["NET_ADMIN"]
DEFAULT_NETWORK_NAME = "app_net"
DEFAULT_DEVICE_NAME = "bridge"

# --- Reserved Keys in Build Configs ---
RESERVED_BUILD_KEYS = {'image', 'volumes', 'cap_add', 'address', 'ref', 'behavior', 'build', 'mixins', 'mounts', 'files', 'auto', 'extra_conf', 'mirror'}

RESERVED_CONFIG_KEYS = {'name', 'inet', 'images', 'builds', 'include', 'auto', 'mirror'}

# -- Config constants ---
MIRRORS = { 
    'apt': ['apt_mirror', 'apt', 'apt_host'], 
    'pip': ['pip_index_url', 'pip_index', 'pip'], 
    'npm': ['npm_registry', 'npm', 'registry'], 
}

# --- Supported os ---
SUPPORTED_OS = ["ubuntu", "debian"]
DEFAULT_OS = "debian"

DEFAULT_PM = "apt"

# --- Package name patterns ---
PKG_NAMES = [
    # Python packages: python3-xxx, python-xxx, pip-xxx, pip3-xxx, py3-xxx, py-xxx
    (r"^(python3|pip3|py3)-(.+)$", "pip3", 2),
    (r"^(python|pip|py)-(.+)$", "pip", 2),
    
    # Node/NPM packages: node-xxx, npm-xxx
    (r"^(node|npm)-(.+)$", "npm", 2),
    
    # Ruby packages: ruby-xxx, gem-xxx
    (r"^(ruby|gem)-(.+)$", "gem", 2),
    
    # Rust packages: rust-xxx, cargo-xxx
    (r"^(rust|cargo)-(.+)$", "cargo", 2),
    
    # Go packages: go-xxx, golang-xxx
    (r"^(go|golang)-(.+)$", "go", 2),
]

BASE_PACKAGE_MANAGERS = {
    "apt": {
        "supported_os": ["ubuntu", "debian", "python"],
        "check_cmd": "command -v apt-get >/dev/null 2>&1",
        "install_cmd": "apt-get update && apt-get install -y --no-install-recommends {packages}",
        "cleanup_cmd": "rm -rf /var/lib/apt/lists/*",
    },
    "dnf": {
        "supported_os": ["fedora", "rhel", "centos"],
        "check_cmd": "command -v dnf >/dev/null 2>&1",
        "install_cmd": "dnf install -y {packages}",
        "cleanup_cmd": "dnf clean all",
    },
    "yum": {
        "supported_os": ["centos", "rhel", "amazonlinux"],
        "check_cmd": "command -v yum >/dev/null 2>&1",
        "install_cmd": "yum install -y {packages}",
        "cleanup_cmd": "yum clean all",
    },
    "apk": {
        "supported_os": ["alpine"],
        "check_cmd": "command -v apk >/dev/null 2>&1",
        "install_cmd": "apk add --no-cache {packages}",
        "cleanup_cmd": "",
    },
}

SOFT_PACKAGE_MANAGERS = {
    "pip": {
        "check_cmd": "command -v pip >/dev/null 2>&1",
        "install_cmd": "pip install --no-cache-dir {packages}",
        "cleanup_cmd": "",
        "base_requirements": {
            "apt": ["python3", "python3-pip"],
            "dnf": ["python3", "python3-pip"],
            "yum": ["python3", "python3-pip"],
            "apk": ["python3", "py3-pip"],
        }
    },
    "pip3": {
        "check_cmd": "command -v pip3 >/dev/null 2>&1",
        "install_cmd": "pip3 install --no-cache-dir {packages}",
        "cleanup_cmd": "",
        "base_requirements": {
            "apt": ["python3", "python3-pip"],
            "dnf": ["python3", "python3-pip"],
            "yum": ["python3", "python3-pip"],
            "apk": ["python3", "py3-pip"],
        }
    },
    "npm": {
        "check_cmd": "command -v npm >/dev/null 2>&1",
        "install_cmd": "npm install -g {packages}",
        "cleanup_cmd": "npm cache clean --force",
        "base_requirements": {
            "apt": ["nodejs", "npm"],
            "dnf": ["nodejs", "npm"],
            "yum": ["nodejs", "npm"],
            "apk": ["nodejs", "npm"],
        }
    },
    "cargo": {
        "check_cmd": "command -v cargo >/dev/null 2>&1",
        "install_cmd": "cargo install {packages}",
        "cleanup_cmd": "",
        "base_requirements": {
            "apt": ["cargo", "rustc"],
            "dnf": ["cargo", "rust"],
            "yum": ["cargo", "rust"],
            "apk": ["cargo", "rust"],
        }
    },
    "go": {
        "check_cmd": "command -v go >/dev/null 2>&1",
        "install_cmd": "go install {packages}",
        "cleanup_cmd": "",
        "base_requirements": {
            "apt": ["golang-go"],
            "dnf": ["golang"],
            "yum": ["golang"],
            "apk": ["go"],
        }
    },
    "gem": {
        "check_cmd": "command -v gem >/dev/null 2>&1",
        "install_cmd": "gem install {packages}",
        "cleanup_cmd": "",
        "base_requirements": {
            "apt": ["ruby", "ruby-dev"],
            "dnf": ["ruby", "ruby-devel"],
            "yum": ["ruby", "ruby-devel"],
            "apk": ["ruby", "ruby-dev"],
        }
    },
}