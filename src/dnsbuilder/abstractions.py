"""
DNS Builder Abstract Base Classes

This module contains all abstract base classes (ABCs) for the DNSBuilder framework.

Dependencies:
- protocols.py: Protocol definitions (structural types)
- datacls/: Data classes (volume, artifacts)
- io/: File system and path abstractions
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple, TypeVar, Generic, Type, TYPE_CHECKING
import logging
import json
import re
import hashlib

from .datacls import BehaviorArtifact, Pair, Package, PkgInstaller
from .io import DNSBPath, FileSystem
from .exceptions import (
    UnsupportedFeatureError,
    DefinitionError,
    ImageDefinitionError,
    BehaviorError,
)
from .rules import Rule, Version
from .utils import deep_merge
from . import constants

if TYPE_CHECKING:
    from .datacls.contexts import BuildContext
    from .registry import ImageRegistry
try:
    from dnslib import RR, NS, CNAME, A, QTYPE
    import ipaddress
except ImportError:
    # Graceful degradation if dnslib not available
    pass
logger = logging.getLogger(__name__)
IMAGE_DEFAULTS = None


# ============================================================================
# Top-level Abstract Base Classes
# ============================================================================

class Image(ABC):
    """
    Abstract class describing a Docker Image.
    
    This is the top-level abstraction for all image types (internal and external).
    """

    def __init__(self, config: Dict[str, Any], fs: FileSystem = None):
        self.name: str = config.get("name")
        self.ref: Optional[str] = config.get("ref")
        if fs is None:
            raise DefinitionError("FileSystem is not provided.")
        self.fs = fs

    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges a parent Image object's attributes with a child's config dict.
        
        Args:
            child_config: The config dict of the child.
        Returns:
            The merged config dict.
        """
        logger.debug(
            f"[{self.name}] [Image] Merging parent '{self.name}' into child '{child_config['name']}'."
        )
        merged = {
            "name": child_config.get("name"),
            "ref": child_config.get("ref"),
        }
        return merged

    @abstractmethod
    def write(self, directory: DNSBPath):
        """
        Writes the image to the specified directory.
        
        Args:
            directory: The directory to write the image to.
        Returns:
            None
        """
        pass


class Behavior(ABC):
    """
    Abstract Class for a DNS server behavior.
    Each behavior can generate its own configuration artifact.
    """

    def __init__(self, zone: str, targets: List[str]):
        self.zone = zone
        self.targets = targets

    @abstractmethod
    def generate(self, service_name: str, build_context: "BuildContext") -> BehaviorArtifact:
        """
        Generates the necessary configuration line and any associated files.
        
        Args:
            service_name: The name of the service this behavior is for.
            build_context: The build context containing all build information.
        Returns:
            A BehaviorArtifact object containing the results.
        """
        pass


class Includer(ABC):
    """
    Abstract Class describe the `include config` line used in software config-file.
    """

    def __init__(self, confs: Dict[str, Pair] = {}, fs: FileSystem = None):
        if fs is None:
            raise DefinitionError("FileSystem is not provided.")
        self.fs = fs
        self.confs = confs
        self.contain()

    @staticmethod
    def parse_blk(pair: Pair) -> Optional[str]:
        """
        parse block name from volume name
        """
        suffixes = DNSBPath(pair.dst).suffixes
        if len(suffixes) >= 1 and suffixes[-1] == ".conf":
            return 'global'

        if len(suffixes) >= 2 and suffixes[-2] == ".conf":
            return suffixes[-1].strip(".")

        raise UnsupportedFeatureError(f"unsupported block format: {pair.dst}")

    @abstractmethod
    def include(self, pair: Pair) -> Optional[Any]:
        """
        write `include config_line` line into conf

        Args:
            pair (Pair): volume pair to include
        Returns:
            Optional[Pair]: the pair to include, if changed
        """
        pass

    @abstractmethod
    def contain(self) -> None:
        """
        contain block-main config in global-main config
        
        Returns:
            None
        """
        pass


# ============================================================================
# Mid-level Abstract Base Classes
# ============================================================================

# ============================================================================
#   Internal Image
# ============================================================================

class InternalImage(Image, ABC):
    """
    Abstract base class for internally-built Docker images.
    
    This class provides common functionality for all images that are built from
    templates (BIND, Unbound, Python, etc.). Subclasses must implement
    _post_init_hook to handle software-specific initialization.
    """
    
    def __init__(self, config: Dict[str, Any], fs: FileSystem = None):
        super().__init__(config, fs)
        self.software: Optional[str] = config.get("software")
        self.version: Optional[str] = config.get("version")
        self.util: List[str] = config.get("util", [])
        self.dependency: List[str] = config.get("dependency", [])
        self.mirror: Dict[str, Any] = config.get("mirror", {})
        self.os, self.os_version = str(config.get("from", ":")).split(":")

        self.default_deps = set()
        self.default_utils = set()
        
        # Cache for Dockerfile content and hash
        self._dcr_cache: Optional[str] = None
        self._img_cache: Optional[str] = None

        if ":" in self.name:
            self._load_defaults()
            self._generate_deps_from_rules()
        self._post_init_hook()
        # os, version is finally determined here, you should not change it anymore
        self.base_image = f"{self.os}:{self.os_version}"
        # never change os, version anymore

        self.dependency = sorted(list(self.default_deps.union(set(self.dependency))))
        self.util = sorted(list(self.default_utils.union(set(self.util))))

        self._parse_packages()

        logger.debug(f"[{self.name}] Final merged dependencies: {self.dependency}")
        logger.debug(f"[{self.name}] Final merged utilities: {self.util}")
        logger.debug(f"[{self.name}] Parsed dep packages: {self.dep_pkgs}")
        logger.debug(f"[{self.name}] Parsed util packages: {self.util_pkgs}")

    @abstractmethod
    def _post_init_hook(self):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
        
        Subclasses must implement this to handle software-specific initialization
        (e.g., processing Python dependencies, setting base OS for Node.js).
        """
        pass

    def _load_defaults(self):
        """Loads default settings from the 'defaults' resource."""
        global IMAGE_DEFAULTS
        if IMAGE_DEFAULTS is None:
            IMAGE_DEFAULTS_TEXT = self.fs.read_text(
                DNSBPath("resource:/images/defaults")
            )
            IMAGE_DEFAULTS = json.loads(IMAGE_DEFAULTS_TEXT)
        if not self.software:
            logger.critical(f"[{self.name}] No SoftWare defined in Image")
            return  # Likely an abstract/alias image without software type

        defaults = IMAGE_DEFAULTS.get(self.software)
        if not defaults:
            logger.warning(
                f"No defaults found for software '{self.software}' in defaults"
            )
            return

        # Load defaults only if this is a preset image
        if ":" in self.name:
            self.os = "ubuntu"  # set actually Ubuntu
            self.base_image = ""  # will be modified later
            self.default_deps = set(defaults.get("default_deps", []))
            self.default_utils = set(defaults.get("default_utils", []))
            logger.debug(
                f"[{self.name}] Initialized with defaults for '{self.software}'."
            )
        else:
            # User-defined image with 'from'
            self.base_image = f"{self.os}:{self.os_version}"
        
    def __os_version(self, dep: str) -> bool:
        """
        Judge a dependency rule for os version or not
        """
        try:
            p = Package.parse(dep, default_pm=None)
            logger.debug(f"{dep} parsed as distinct {p.__repr__}, not a os version")
            return False
        except Exception:
            logger.debug(f"{dep} parsed as not distince package, may be os version.")
            pass

        if "." in dep:
            # like ubuntu:12.04, python:3.9-slim etc.
            return True
        else:
            # like debian:12, node:14 etc.
            try:
                int(dep)
                return True
            except Exception:
                pass
        return False

    def _generate_deps_from_rules(self):
        """
        Parses the rule set for the given software version to determine
        the base OS version and additional dependencies.
        """
        if not self.software or not self.version:
            logger.critical(f"[{self.name}] No SoftWare or No Version defined in Image")
            return  # Not a buildable image

        try:
            rules_text = self.fs.read_text(
                DNSBPath(f"resource:/images/rules/{self.software}")
            )
            ruleset = json.loads(rules_text)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ImageDefinitionError(f"Failed to load rules for '{self.software}': {e}")

        version_obj = Version(self.version)
        is_valid = False
        os_version_from_rule = None

        for raw_rule, dep in ruleset.items():
            rule = Rule(raw_rule)
            if version_obj not in rule:
                continue

            if dep is None:
                # Version Validation
                is_valid = True
            elif self.__os_version(dep):
                # OS Version Fetch
                if not os_version_from_rule:
                    os_version_from_rule = dep
            else:
                # Added Dependency
                logger.debug(
                    f"[{self.name}] Rule '{raw_rule}' met, adding dependency '{dep}'."
                )
                self.default_deps.add(dep)

        if not is_valid:
            raise ImageDefinitionError(
                f"[{self.name}] Version '{self.version}' is not valid according to the ruleset."
            )

        if os_version_from_rule:
            self.os_version = os_version_from_rule
            self.base_image = f"{self.os}:{self.os_version}"
            logger.debug(
                f"[{self.name}] OS version set to '{os_version_from_rule}' by rule."
            )
        elif ":" in self.name and not self.os_version:
            raise ImageDefinitionError(
                f"[{self.name}] Failed to determine OS version from rules for version '{self.version}'."
            )

    def _parse_packages(self):
        """
        Parse merged packages into Package objects for installation.
        Uses set to deduplicate packages that may appear in different formats.
        """
        self.installer = PkgInstaller(self.os)
        self.dep_pkgs = sorted(list(set(self.installer.parse(self.dependency))), key=str)
        self.util_pkgs = sorted(list(set(self.installer.parse(self.util))), key=str)

    def _generate_dockerfile_content(self) -> str:
        """
        Loads the appropriate Dockerfile template and formats it with instance variables.
        Subclasses can override this to provide additional template variables.
        Result is cached to avoid redundant generation.
        """
        # Return cached content if available
        if self._dcr_cache is not None:
            return self._dcr_cache
        
        try:
            template = self.fs.read_text(
                DNSBPath(f"resource:/images/templates/{self.software}")
            )
        except FileNotFoundError:
            raise ImageDefinitionError(f"Dockerfile template for '{self.software}' not found.")

        template_vars = self._get_template_vars()
        self._dcr_cache = template.format(**template_vars)
        return self._dcr_cache

    def _get_template_vars(self) -> Dict[str, Any]:
        """Provides a dictionary of variables for formatting the Dockerfile template."""
        dep_packages = self.installer.gen_cmds(self.dep_pkgs, "build")
        util_packages = self.installer.gen_cmds(self.util_pkgs, "runtime")
        # chsrc installation (if any mirror uses 'auto')
        chsrc_install_setup = self._chsrc_install()
        # Mirror injections (optional)
        apt_mirror_setup = self.apt_mro()
        pip_mirror_setup = self.pip_mro()
        npm_registry_setup = self.npm_mro()
        return {
            "name": self.name,
            "version": self.version,
            "base_image": self.base_image,
            "dep_packages": dep_packages,
            "util_packages": util_packages,
            "chsrc_install_setup": chsrc_install_setup,
            "apt_mirror_setup": apt_mirror_setup,
            "pip_mirror_setup": pip_mirror_setup,
            "npm_registry_setup": npm_registry_setup,
        }

    def get_image_hash(self) -> str:
        """Generate a unique hash for this image configuration based on Dockerfile content.
        Result is cached to avoid redundant hashing."""
        # Return cached hash if available
        if self._img_cache is not None:
            return self._img_cache
        
        content = self._generate_dockerfile_content()
        self._img_cache = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self._img_cache

    def get_tag(self) -> str:
        """Generate a unique image tag for sharing across services with identical configurations."""
        image_hash = self.get_image_hash()
        return f"dnsb-{self.software}-{self.version}-{image_hash}"

    def _needs_chsrc(self) -> bool:
        """Check if any mirror configuration uses 'auto' (requires chsrc)"""
        if not self.mirror:
            return False
        
        # Check all supported mirror types for 'auto' value
        for mirror_type in constants.MIRRORS.keys():
            for key in constants.MIRRORS.get(mirror_type, []):
                if self.mirror.get(key) == "auto":
                    return True
        return False
    
    def _chsrc_install(self) -> str:
        """Generate chsrc installation commands if needed"""
        if not self._needs_chsrc():
            return ""
        
        # Determine architecture based on base image
        arch = "x64"
        
        install_cmd = (
            "# Install chsrc for automatic mirror source switching\n"
            "RUN set -eux; \\\n"
            "    if command -v wget >/dev/null 2>&1; then \\\n"
            f"        wget -O /tmp/chsrc https://gitee.com/RubyMetric/chsrc/releases/download/pre/chsrc-{arch}-linux; \\\n"
            "    elif command -v curl >/dev/null 2>&1; then \\\n"
            f"        curl -L https://gitee.com/RubyMetric/chsrc/releases/download/pre/chsrc-{arch}-linux -o /tmp/chsrc; \\\n"
            "    else \\\n"
            "        # Temporarily use a fast mirror to install curl\n"
            "        sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true; \\\n"
            "        sed -i 's|archive.ubuntu.com|mirrors.ustc.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true; \\\n"
            "        apt-get update && apt-get install -y --no-install-recommends curl && \\\n"
            f"        curl -k https://gitee.com/RubyMetric/chsrc/releases/download/pre/chsrc-{arch}-linux -o /tmp/chsrc && \\\n"
            "        rm -rf /var/lib/apt/lists/*; \\\n"
            "    fi && \\\n"
            "    chmod +x /tmp/chsrc"
        )
        
        logger.debug(f"[{self.name}] chsrc installation will be added to Dockerfile")
        return install_cmd

    def apt_mro(self) -> str:
        """Generate APT mirror configuration"""
        # Support multiple key aliases for convenience
        mirror_value = ""
        for key in constants.MIRRORS["apt"]:
            if key in self.mirror:
                mirror_value = self.mirror[key]
                break
        
        if not mirror_value:
            return ""
        
        if mirror_value == "auto":
            _apt_defined = constants.SUPPORTED_OS
            base_os = self.os if self.os in _apt_defined else constants.DEFAULT_OS
            return f"RUN /tmp/chsrc set {base_os} first || true"
        
        # Manual mode - use specified mirror URL
        url = DNSBPath(mirror_value)
        mirror_host = url.host or url.__path__()
        if not mirror_host:
            logger.warning(f"[{self.name}] Invalid apt mirror host: {mirror_value}")
            return ""
        proto = "http" if url.is_http() else "https"
        _apt_defined = constants.SUPPORTED_OS
        base_os = self.os if self.os in _apt_defined else constants.DEFAULT_OS
        if base_os == "ubuntu":
            # Properly escape dots in sed patterns
            return (
                f"RUN sed -i 's|archive\\.ubuntu\\.com|{mirror_host}|g' /etc/apt/sources.list && "
                f"sed -i 's|security\\.ubuntu\\.com|{mirror_host}|g' /etc/apt/sources.list"
            )
        if base_os == "debian":
            return (
                "RUN set -eux; "
                "if [ -f /etc/apt/sources.list.d/debian.sources ]; then "
                f"sed -i 's|deb\\.debian\\.org|{mirror_host}|g' /etc/apt/sources.list.d/debian.sources; "
                f"sed -i 's|security\\.debian\\.org|{mirror_host}|g' /etc/apt/sources.list.d/debian.sources; "
                "elif [ -f /etc/apt/sources.list ]; then "
                f"sed -i 's|deb\\.debian\\.org|{mirror_host}|g' /etc/apt/sources.list; "
                f"sed -i 's|security\\.debian\\.org|{mirror_host}|g' /etc/apt/sources.list; "
                "else "
                "codename=$(grep VERSION_CODENAME /etc/os-release | cut -d= -f2 || echo bookworm); "
                f"echo \"deb {proto}://{mirror_host}/debian ${{codename}} main contrib non-free non-free-firmware\" > /etc/apt/sources.list; "
                f"echo \"deb {proto}://{mirror_host}/debian ${{codename}}-updates main contrib non-free non-free-firmware\" >> /etc/apt/sources.list; "
                f"echo \"deb {proto}://{mirror_host}/debian-security ${{codename}}-security main contrib non-free non-free-firmware\" >> /etc/apt/sources.list; "
                "fi"
            )
        return ""

    def pip_mro(self) -> str:
        """Generate pip mirror configuration"""
        mirror_value = ""
        for key in constants.MIRRORS["pip"]:
            if key in self.mirror:
                mirror_value = self.mirror[key]
                break
        
        if not mirror_value:
            return ""
        
        # Handle 'auto' mode - use chsrc first
        if mirror_value == "auto":
            return "RUN /tmp/chsrc set pip first || true"
        
        # Manual mode - use specified index URL
        return f"RUN pip config set global.index-url {mirror_value} || true"

    def npm_mro(self) -> str:
        """Generate npm mirror configuration"""
        mirror_value = ""
        for key in constants.MIRRORS["npm"]:
            if key in self.mirror:
                mirror_value = self.mirror[key]
                break
        
        if not mirror_value:
            return ""
        
        # Handle 'auto' mode - use chsrc first
        if mirror_value == "auto":
            return "RUN /tmp/chsrc set npm first || true"
        
        # Manual mode - use specified registry URL
        return f"RUN npm config set registry {mirror_value} || true"

    def write(self, directory: DNSBPath) -> Optional[str]:
        """Write Dockerfile to shared images directory and return the shared image tag.
        
        Args:
            directory: Service directory
            
        Returns:
            The shared image tag if buildable, None otherwise
        """
        if not self.software or not self.version:
            logger.debug(
                f"Image '{self.name}' is not buildable (likely an alias), skipping Dockerfile generation."
            )
            return None

        content = self._generate_dockerfile_content()
        image_hash = self.get_image_hash()
        output_dir = directory.parent
        shared_dir = output_dir / ".images" / image_hash

        self.fs.mkdir(shared_dir, parents=True, exist_ok=True)
        dockerfile_path = shared_dir / "Dockerfile"
        
        # Only write if doesn't exist (avoid redundant writes)
        if not self.fs.exists(dockerfile_path):
            self.fs.write_text(dockerfile_path, content)
            logger.info(f"Shared Dockerfile for '{self.name}' written to {dockerfile_path}")
        else:
            logger.debug(f"Shared Dockerfile for '{self.name}' already exists at {dockerfile_path}")
        
        # Write a hook
        hook_path = directory / "docker.hook"
        self.fs.write_text(hook_path, f"# Dockerfile located at: {dockerfile_path}\n# Tag to use: {self.get_tag()}\n")

        # Return the shared image tag for docker-compose
        return self.get_tag()

    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges a parent Image object's attributes with a child's config dict.
        Child's config takes precedence. Lists are merged (union).
        """
        import copy
        
        merged = super().merge(child_config)
        logger.debug(
            f"[{self.name}] [InternalImage] Merging parent '{self.name}' into child '{child_config['name']}'."
        )
        parent_values = {
            "from": f"{self.os}:{self.os_version}",
            "software": self.software,
            "version": self.version,
            "dependency": [str(pkg) for pkg in self.dep_pkgs],
            "util": [str(pkg) for pkg in self.util_pkgs],
            "mirror": copy.deepcopy(self.mirror)
        }
        merged.update(parent_values)
        merged["software"] = child_config.get("software", merged["software"])
        merged["version"] = child_config.get("version", merged["version"])
        parent_mirror = merged.get("mirror") or {}
        child_mirror = child_config.get("mirror") or {}
        merged["mirror"] = deep_merge(parent_mirror, child_mirror)

        child_deps = set(child_config.get("dependency", []))
        child_utils = set(child_config.get("util", []))
        merged["dependency"] = sorted(list(set(merged["dependency"]).union(child_deps)))
        merged["util"] = sorted(list(set(merged["util"]).union(child_utils)))
        logger.debug(
            f"[{self.name}] [InternalImage] Merge result for '{child_config['name']}': {merged}"
        )
        return merged


# ============================================================================
#   External Image
# ============================================================================

class ExternalImage(Image, ABC):
    """
    Abstract base class for external Docker images.
    
    External images are not built from templates but are either:
    - Docker Hub images (referenced by name)
    - Self-defined images (user provides a Dockerfile path)
    """

    def __init__(self, config: Dict[str, Any], fs: FileSystem = None):
        super().__init__(config, fs)
        self.fs = fs
        self.software: Optional[str] = None
        self.original_name = self.name
        
        # Parse software type from placeholder in name and clean the name
        self._parse_software()
        self._post_init_hook(config)

    def _parse_software(self):
        """
        Parse software type from placeholder in name and clean the name.
        Falls back to regex recognition and finally to 'NAS' if no supported type is found.
        """
        # Import registry lazily to avoid circular dependency
        from .registry import image_registry
        
        if not self.name:
            self.software = "NaS"
            logger.debug(f"[{self.original_name}] No name provided, defaulting to Not a Service")
            return
        
        placeholder_pattern = r'\$\{([^\}]+)\}'
        matches = re.findall(placeholder_pattern, self.name)
        supported_software = image_registry.get_supports()
        
        if matches:
            placeholder_content = matches[0].strip()
            
            # Check if the placeholder content is a supported software type
            if placeholder_content in supported_software:
                self.software = placeholder_content
                logger.debug(f"[{self.original_name}] Software type extracted from placeholder: {self.software}")
            else:
                logger.debug(f"[{self.original_name}] Placeholder '{placeholder_content}' is not a supported software type")
                # Fall back to regex recognition on the placeholder content
                self.software = self._rec_software_from_name(placeholder_content)
                if self.software == "NaS":
                    self.software = self._rec_software_from_name(self.name)
            
            cleaned_name = re.sub(placeholder_pattern, "", self.name)
            if cleaned_name:
                self.name = cleaned_name
                logger.debug(
                    f"[{self.original_name}] Name cleaned from '{self.original_name}' to '{self.name}'"
                )
            else:
                # If cleaning results in empty name, use a default name
                self.name = "external"
                logger.debug(
                    f"[{self.original_name}] Name cleaned to '{self.name}' (default name used)"
                )
        else:
            # No placeholder found, try regex recognition on the full name
            self.software = self._rec_software_from_name(self.name)
            logger.debug(f"[{self.original_name}] No placeholder found, software type from regex: {self.software}")
        
        # Final fallback to NaS if still not determined
        if not self.software or self.software == "NaS":
            self.software = "NaS"
            logger.debug(f"[{self.original_name}] Final fallback to Not a Service")

    def _rec_software_from_name(self, name: str) -> str:
        """
        Use regex patterns to recognize software type from image name.
        
        Args:
            name: The image name to analyze
            
        Returns:
            Recognized software type or 'NaS' if not found
        """
        # Import registry lazily to avoid circular dependency
        from .registry import image_registry
        
        supported_software = image_registry.get_supports()
        name_lower = name.lower()
        for soft in constants.RECOGNIZED_PATTERNS.keys():
            if soft in supported_software:
                for pattern in constants.RECOGNIZED_PATTERNS[soft]:
                    if re.search(pattern, name_lower):
                        return soft
            else:
                logger.debug(f"[{self.original_name}] Software type '{soft}' is not supported, passed.")
        return "NaS"

    @abstractmethod
    def _post_init_hook(self, config: Dict[str, Any]):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
        
        Subclasses must implement this (e.g., DockerImage does nothing,
        SelfDefinedImage validates and finds the Dockerfile path).
        """
        pass

    @abstractmethod
    def write(self, directory: DNSBPath):
        """
        Write image artifacts to the specified directory.
        
        For external images, this typically does nothing or copies user-provided files.
        """
        logger.debug(
            f"[{self.name}] [ExternalImage] Image '{self.name}' is an external image, skipping Dockerfile generation."
        )
        return


# ============================================================================
#   Master Behavior
# ============================================================================

class MasterBehavior(Behavior, ABC):
    """
    Abstract base class for master/authoritative zone behaviors.
    
    This class provides common functionality for behaviors that generate
    authoritative DNS zone records. Subclasses must implement generate_config_line
    to produce software-specific configuration.
    """

    def __init__(self, zone: str, args_str: str):
        # zone is the target zone file name, e.g. "com" for "db.com"
        # args_str is the record, e.g. "example.com A 1.2.3.4"
        self.zone_file_key = zone
        rname, self.record_type, targets_str, self.ttl = self._parse_args(args_str)
        # Use rname as the 'zone' for the base Behavior class, which it uses as rname
        super().__init__(rname, [t.strip() for t in targets_str.split(",")])

    def _parse_args(self, args_str: str) -> Tuple[str, str, str, int]:
        """Parse record args from origin string"""
        # Expected format: "<rname> <type> <ttl> <target1>,<target2>..."
        parts = args_str.strip().split(maxsplit=3)
        ttl = 3600
        if len(parts) == 4:
            try:
                ttl = int(parts[2])
            except Exception:
                logger.warning(
                    f"Invalid TTL value '{parts[2]}' for record '{parts[0]}' in zone '{self.zone_file_key}'. "
                    f"Using default TTL."
                )
                pass
        elif len(parts) == 3:
            pass
        elif len(parts) != 3:
            raise UnsupportedFeatureError(
                f"Invalid 'master' behavior format for zone '{self.zone_file_key}'. "
                f"Expected '<record-name> <type> [<ttl>] <target1>,<target2>...', got '{args_str}'."
            )
        # rname, rtype, targets_str, ttl
        return parts[0], parts[1].upper(), parts[-1], ttl

    @abstractmethod
    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """
        Generate configuration line for this behavior.
        
        This method must be implemented by subclasses to generate software-specific
        configuration (e.g., BIND's 'zone "example.com" { type master; file "..."; };').
        
        Args:
            zone_name: The zone name
            file_path: Path to the zone file
            
        Returns:
            Configuration line string
        """
        pass

    def generate(
        self, service_name: str, build_context: "BuildContext"
    ) -> BehaviorArtifact:
        """Generate behavior artifact for this behavior, handling different record types."""
        records = []
        try:
            rtype_id = getattr(QTYPE, self.record_type)
        except AttributeError:
            raise UnsupportedFeatureError(
                f"Unsupported record type '{self.record_type}'."
            )

        rname = self.get_rname(self.zone, self.zone_file_key)

        if self.record_type in ("A", "AAAA"):
            target_ips = self.resolve_ips(self.targets, build_context, service_name)
            record_class = constants.RECORD_TYPE_MAP.get(self.record_type)
            if not record_class:
                raise UnsupportedFeatureError(
                    f"Unsupported record type '{self.record_type}'."
                )  # Should not happen
            records.extend(
                [
                    RR(rname=rname, rtype=rtype_id, rdata=record_class(ip), ttl=self.ttl)
                    for ip in target_ips
                ]
            )

        elif self.record_type == "NS":
            for target in self.targets:
                # Check for and generate glue records
                target_ip = build_context.service_ips.get(target)
                if target_ip:
                    # Use service name as NS domain: {service}.servers.net.
                    ns_name = f"{target}.servers.net."
                    logger.debug(f"Generated NS record with glue: {ns_name} -> {target_ip} (service: {target})")
                    records.append(
                        RR(
                            rname=rname,
                            rtype=rtype_id,
                            rdata=NS(ns_name),
                            ttl=self.ttl,
                        )
                    )
                    records.append(
                        RR(
                            rname=ns_name,
                            rtype=QTYPE.A,
                            rdata=A(target_ip),
                            ttl=self.ttl
                        )
                    )
                else:
                    # External
                    records.append(
                        RR(rname=rname, rtype=rtype_id, rdata=NS(self.get_rname(target, self.zone_file_key)), ttl=self.ttl)
                    )

        elif self.record_type == "CNAME":
            for target_domain in self.targets:
                records.append(
                    RR(rname=rname, rtype=rtype_id, rdata=CNAME(self.get_rname(target_domain, self.zone_file_key)), ttl=self.ttl)
                )

        else:
            # For other types like TXT, treat targets as string data
            record_class = constants.RECORD_TYPE_MAP.get(self.record_type)
            if not record_class:
                raise UnsupportedFeatureError(
                    f"Unsupported record type '{self.record_type}' in master behavior for zone '{rname}'."
                )
            # TXT rdata needs to be a list of strings/bytes
            rdata_val = [self.get_rname(t, self.zone_file_key).encode("utf-8") for t in self.targets]
            records.append(
                RR(
                    rname=rname,
                    rtype=rtype_id,
                    rdata=record_class(rdata_val),
                    ttl=self.ttl,
                )
            )

        return BehaviorArtifact(config_line="", new_records=records)

    @staticmethod
    def resolve_ips(
        targets: List[str], build_context: "BuildContext", service_name: str, ignore: bool = False
    ) -> List[str]:
        """Resolves a list of behavior targets, which can be service names or IPs."""
        resolved_ips = []
        for target in targets:
            try:
                ipaddress.ip_address(target)
                resolved_ips.append(target)
                continue
            except ValueError:
                pass  # Not an IP, assume it's a service name

            target_ip = build_context.service_ips.get(target)
            if not target_ip:
                if ignore:
                    continue
                raise BehaviorError(
                    f"Behavior in '{service_name}' references an undefined service or invalid IP: '{target}'."
                )
            resolved_ips.append(target_ip)
        return resolved_ips

    @staticmethod
    def get_rname(origin: str, zone: str) -> str:
        """Get the full record name from origin and zone"""
        if origin == '@':
            rname = zone
        elif not origin.endswith('.'):
            if zone == ".":
                rname = f"{origin}."
            else:
                rname = f"{origin}.{zone}"
        else:
            rname = origin
        return rname

