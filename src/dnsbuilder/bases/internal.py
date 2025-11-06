from abc import ABC, abstractmethod
import copy
import json
from typing import Any, Dict, List, Optional
import logging

from ..utils.typing_compat import override
from ..base import Image
from ..rules.rule import Rule
from ..rules.version import Version
from ..io.path import DNSBPath
from ..io.fs import FileSystem, AppFileSystem
from ..exceptions import ImageDefinitionError
from ..utils.merge import deep_merge

logger = logging.getLogger(__name__)

# Global variable to cache image defaults
IMAGE_DEFAULTS = None

# -------------------------
#
#   INTERNAL IMAGE
#
# -------------------------

class InternalImage(Image, ABC):
    def __init__(self, config: Dict[str, Any], fs: FileSystem = AppFileSystem()):
        super().__init__(config, fs)
        self.software: Optional[str] = config.get("software")
        self.version: Optional[str] = config.get("version")
        self.util: List[str] = config.get("util", [])
        self.dependency: List[str] = config.get("dependency", [])
        # Optional mirror configuration for package managers
        self.mirror: Dict[str, Any] = config.get("mirror", {})
        self.os, self.os_version = str(config.get("from", ":")).split(":")

        self.base_image = f"{self.os}:{self.os_version}"
        self.default_deps = set()
        self.default_utils = set()

        if ":" in self.name:
            self._load_defaults()
            self._generate_deps_from_rules()
        self._post_init_hook()

        # Final merge of default, rule-based, and user-defined dependencies
        self.dependency = sorted(list(self.default_deps.union(set(self.dependency))))
        self.util = sorted(list(self.default_utils.union(set(self.util))))

        logger.debug(f"[{self.name}] Final merged dependencies: {self.dependency}")
        logger.debug(f"[{self.name}] Final merged utilities: {self.util}")

    @abstractmethod
    def _post_init_hook(self):
        """
        A hook for subclasses to run specific logic after the main __init__ setup.
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

    def _generate_dockerfile_content(self) -> str:
        """
        Loads the appropriate Dockerfile template and formats it with instance variables.
        Subclasses can override this to provide additional template variables.
        """
        try:
            template = self.fs.read_text(
                DNSBPath(f"resource:/images/templates/{self.software}")
            )
        except FileNotFoundError:
            raise ImageDefinitionError(f"Dockerfile template for '{self.software}' not found.")

        template_vars = self._get_template_vars()
        return template.format(**template_vars)

    def _get_template_vars(self) -> Dict[str, Any]:
        """Provides a dictionary of variables for formatting the Dockerfile template."""
        dep_packages = " ".join(self.dependency)
        util_packages = " ".join(self.util)
        # Mirror injections (optional)
        apt_mirror_setup = self._apt_mro()
        pip_mirror_setup = self._pip_mro()

        return {
            "name": self.name,
            "version": self.version,
            "base_image": self.base_image,
            "dep_packages": dep_packages,
            "util_packages": util_packages or "''",
            "apt_mirror_setup": apt_mirror_setup,
            "pip_mirror_setup": pip_mirror_setup,
        }

    def _apt_mro(self) -> str:
        # Support multiple key aliases for convenience
        mirror_host_origin = (
            self.mirror.get("apt_mirror")
            or self.mirror.get("apt")
            or self.mirror.get("apt_host")
        )
        if not mirror_host_origin:
            return ""
        url = DNSBPath(mirror_host_origin)
        mirror_host = url.host or url.__path__()
        if not mirror_host:
            logger.warning(f"[{self.name}] Invalid apt mirror host: {mirror_host_origin}")
            return ""
        proto = "http" if url.is_http() else "https"
        _apt_defined = ["ubuntu", "debian"]
        base_os = self.os if self.os in _apt_defined else "debian"
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

    def _pip_mro(self) -> str:
        index_url = (
            self.mirror.get("pip_index_url")
            or self.mirror.get("pip_index")
            or self.mirror.get("pip")
        )
        if not index_url:
            return ""
        # Use pip config to persist across pip calls
        return f"RUN pip config set global.index-url {index_url} || true"

    def write(self, directory: DNSBPath):
        if not self.software or not self.version:
            logger.debug(
                f"Image '{self.name}' is not buildable (likely an alias), skipping Dockerfile generation."
            )
            return

        content = self._generate_dockerfile_content()
        dockerfile_path = directory / "Dockerfile"
        self.fs.write_text(dockerfile_path, content)
        logger.debug(f"Dockerfile for '{self.name}' written to {dockerfile_path}")

    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges a parent Image object's attributes with a child's config dict.
        Child's config takes precedence. Lists are merged (union).
        """
        merged = super().merge(child_config)
        logger.debug(
            f"[{self.name}] [InternalImage] Merging parent '{self.name}' into child '{child_config['name']}'."
        )
        parent_values = {
            "from": f"{self.os}:{self.os_version}",
            "software": self.software,
            "version": self.version,
            "dependency": copy.deepcopy(self.dependency),
            "util": copy.deepcopy(self.util),
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

# -------------------------
#
#   BIND IMAGE
#
# -------------------------

class BindImage(InternalImage):
    """
    Concrete Image class for BIND
    """

    def __init__(self, config: Dict[str, Any], fs: FileSystem = AppFileSystem()):
        self.py3_deps = []  # will init in hook
        super().__init__(config, fs=fs)

    @override
    def _post_init_hook(self):
        """
        Handle BIND's specific python3 dependency logic after base setup.
        """
        py3_pkg_names = [
            dep.split("python3-")[-1] for dep in self.dependency if "python3-" in dep
        ]

        if "pip" in py3_pkg_names:
            py3_pkg_names.remove("pip")

        self.py3_deps = sorted(list(set(py3_pkg_names)))

        if self.py3_deps:
            self.dependency = [dep for dep in self.dependency if "python3-" not in dep]
            self.dependency.extend(["python3", "python3-pip"])
            logger.debug(
                f"[{self.name}] Processed Python dependencies: {self.py3_deps}"
            )

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        """
        Extend base template variables with BIND-specific ones.
        """
        base_vars = super()._get_template_vars()
        py3_packages = " ".join(self.py3_deps)
        base_vars["py3_packages"] = (
            f"RUN pip3 install {py3_packages}" if py3_packages else ""
        )
        return base_vars

    @override
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure python3 dependencies from the parent are correctly carried over.
        """
        merged = super().merge(child_config)
        # Re-add the python3- prefixed deps for accurate merging with child deps
        merged["dependency"].extend([f"python3-{dep}" for dep in self.py3_deps])
        merged["dependency"] = sorted(list(set(merged["dependency"])))
        logger.debug(f"[{self.name}] [BindImage] Fully Merged Result : {merged}")
        return merged

# -------------------------
#
#   UNBOUND IMAGE
#
# -------------------------

class UnboundImage(InternalImage):
    """
    Concrete Image class for Unbound.
    """

    @override
    def _post_init_hook(self):
        """
        Nothing to do
        """
        pass  # Unbound has nothing to do

# ------------------------
#
#   JUDAS IMAGE
#
# ------------------------

class JudasImage(InternalImage):
    """
    Concrete Image class for JudasDNS
    """

    @override
    def _post_init_hook(self):
        """
        Handle JudasDNS's specific dependency logic after base setup.
        """
        self.os = "node"

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        base_vars = super()._get_template_vars()
        npm_registry = (
            self.mirror.get("npm_registry")
            or self.mirror.get("npm")
            or self.mirror.get("registry")
        )
        base_vars["npm_registry_setup"] = (
            f"RUN npm config set registry {npm_registry}" if npm_registry else ""
        )
        return base_vars

# -------------------------
#
#   PYTHON IMAGE
#
# -------------------------

class PythonImage(InternalImage):
    """
    Concrete Image class for Python
    """

    def __init__(self, config: Dict[str, Any], fs: FileSystem = AppFileSystem()):
        self.pip_deps = []
        super().__init__(config, fs=fs)

    @override
    def _load_defaults(self):
        super()._load_defaults()
        if ":" in self.name:
            # ensure the base os is 'python', not 'ubuntu'
            self.os = "python"

    @override
    def _post_init_hook(self):
        """
        Handle Python's specific dependency logic.
        """
        self.dependency = []

        pip_pkg_names = [
            dep.split("python3-")[-1] for dep in self.util if dep.startswith("python3-")
        ]

        self.pip_deps = sorted(list(set(pip_pkg_names)))

        if self.pip_deps:
            # Filter out pip packages from the system utility list
            self.util = [dep for dep in self.util if not dep.startswith("python3-")]
            logger.debug(
                f"[{self.name}] Processed Python pip dependencies: {self.pip_deps}"
            )

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        """
        Extend base template variables with Python-specific ones.
        """
        base_vars = super()._get_template_vars()
        pip_packages = " ".join(self.pip_deps)
        base_vars["pip_packages"] = (
            f"RUN pip install --no-cache-dir {pip_packages}" if pip_packages else ""
        )
        # Ensure dep_packages is empty for the template
        base_vars["dep_packages"] = ""
        return base_vars

    @override
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure python dependencies from the parent are correctly carried over.
        """
        merged = super().merge(child_config)
        # Re-add the python3- prefixed deps to the 'util' list for accurate merging
        merged["util"].extend([f"python3-{dep}" for dep in self.pip_deps])
        merged["util"] = sorted(list(set(merged["util"])))
        logger.debug(f"[{self.name}] [PythonImage] Fully Merged Result : {merged}")
        return merged