from enum import Enum

# --- Filenames and Paths ---
GENERATED_ZONES_FILENAME = "generated_zones.conf"
GENERATED_ZONES_SUBDIR = "zones"
DOCKERFILE_NAME = "Dockerfile"
DOCKER_COMPOSE_FILENAME = "docker-compose.yml"

# --- Prefixes ---
RESOURCE_PREFIX = "resource:"
STD_BUILD_PREFIX = "std:"

# --- Software Types ---
SOFTWARE_BIND = "bind"
SOFTWARE_UNBOUND = "unbound"

# --- Behavior Sections ---
class BehaviorSection(str, Enum):
    SERVER = "server"
    TOPLEVEL = "toplevel"

# --- Docker Compose Keys & Values ---
DEFAULT_CAP_ADD = ["NET_ADMIN"]
DEFAULT_NETWORK_NAME = "app_net"
DEFAULT_DEVICE_NAME = "bridge"

# --- Reserved Keys in Build Configs ---
RESERVED_BUILD_KEYS = {'image', 'volumes', 'cap_add', 'address', 'ref', 'behavior', 'build', "mixins", "mounts"}

RESERVED_CONFIG_KEYS = {'name', 'inet', 'images', 'builds', 'include'}