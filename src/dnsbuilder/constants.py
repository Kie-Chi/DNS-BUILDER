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
DOCKERFILE_NAME = "Dockerfile"
DOCKER_COMPOSE_FILENAME = "docker-compose.yml"

# --- Prefixes ---
RESOURCE_PREFIX = "resource:"
STD_BUILD_PREFIX = "std:"

# --- Software Configuration ---
SOFTWARE_BIND = "bind"
SOFTWARE_UNBOUND = "unbound"

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
    }
}

RECOGNIZED_PATTERNS = {
    "bind": [
        r"\bbind\b",  # exact word match
        r"\bisc-bind\b",  # ISC BIND
        r"\bnamed\b",  # BIND daemon name
    ],
    "unbound": [
        r"\bunbound\b"  # exact word match
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

# --- supported os ---
SUPPORTED_OS = ["ubuntu", "debian"]
DEFAULT_OS = "debian"