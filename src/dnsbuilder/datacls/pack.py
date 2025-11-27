# ============================================================================
# Package Management Classes
# ============================================================================

from typing import List, Dict, Optional, Tuple
from pydantic import BaseModel, Field, validator
import re
import logging

from ..exceptions import UnsupportedFeatureError
from .. import constants

logger = logging.getLogger(__name__)

class Package(BaseModel):
    """
    Represents a software package and its installation method.
    """
    name: str
    pm: str = Field(default="apt")
    is_base: bool = Field(default=False, init=False)
    is_soft: bool = Field(default=False, init=False)
    
    class Config:
        # Allow string construction
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        # Support Package("curl") or Package(name="curl")
        if len(data) == 1 and 'name' not in data:
            pkg_str = list(data.values())[0]
            parsed = self.parse(pkg_str)
            data = {'name': parsed.name, 'pm': parsed.pm}
        
        super().__init__(**data)
        self.is_base = self.pm in constants.BASE_PACKAGE_MANAGERS
        self.is_soft = self.pm in constants.SOFT_PACKAGE_MANAGERS
        
        if not self.is_base and not self.is_soft:
            raise UnsupportedFeatureError(f"Unknown PM '{self.pm}' for '{self.name}'")
    
    @validator('name', 'pm', pre=True)
    def strip_whitespace(cls, v):
        return v.strip() if isinstance(v, str) else v
    
    @validator('pm')
    def lowercase_pm(cls, v):
        return v.lower()
    
    @classmethod
    def __get_validators__(cls):
        """Pydantic custom validator"""
        yield cls.validate
    
    @classmethod
    def validate(cls, v):
        """Validate package string"""
        if isinstance(v, str):
            return cls.parse(v)
        elif isinstance(v, cls):
            return v
        elif isinstance(v, dict):
            return cls(**v)
        raise TypeError(f'Cannot convert {type(v)} to Package')
    
    @classmethod
    def parse(cls, s: str, default_pm: str = constants.DEFAULT_PM, auto_detect: bool = True) -> "Package":
        """Parse package string"""
        s = s.strip()
        
        if ":" in s:
            name, pm = s.rsplit(":", 1)
            if pm in constants.SOFT_PACKAGE_MANAGERS or pm in constants.BASE_PACKAGE_MANAGERS:
                return cls(name=name.strip(), pm=pm.strip())
        
        if auto_detect:
            for pattern, pm, group_idx in constants.PKG_NAMES:
                match = re.match(pattern, s)
                if match:
                    clean_name = match.group(group_idx)
                    logger.debug(f"Auto-detected: '{s}' -> Package('{clean_name}', '{pm}')")
                    return cls(name=clean_name, pm=pm)
        
        return cls(name=s, pm=default_pm)
    
    def __str__(self):
        return f"{self.name}:{self.pm}"
    
    def __repr__(self):
        return f"Package({self.name}, {self.pm})"
    
    def __hash__(self):
        return hash((self.name, self.pm))


class PkgInstaller:
    """
    Generate package installation commands for Dockerfile.
    
    Handles:
    - Base and soft package manager dependencies
    - Command grouping and optimization
    - Auto-installation of soft PM requirements
    """
    
    def __init__(self, os: str, base_pm: Optional[str] = None):
        """
        Args:
            os: Base OS name (ubuntu, debian, etc.)
            base_pm: Base package manager, auto-detect if None
        """
        self.os = os
        self.base_pm = base_pm or self._get_base_pm()
        self._installed_prereqs: set = set()
        logger.debug(f"PkgInstaller: os={os}, base_pm={self.base_pm}")
    
    def _get_base_pm(self):
        for pm in constants.BASE_PACKAGE_MANAGERS.keys():
            if self.os in constants.BASE_PACKAGE_MANAGERS[pm]['supported_os']:
                return pm
        return constants.DEFAULT_PM

    def parse(self, pkgs: List[str]) -> List[Package]:
        """Parse package strings into Package objects."""
        return [Package.parse(pkg, default_pm=self.base_pm, auto_detect=True) for pkg in pkgs]

    def group(self, pkgs: List[Package]) -> Dict[str, List[str]]:
        """Group packages by their package manager."""
        grouped = {}
        for pkg in pkgs:
            if pkg.pm != self.base_pm and pkg.pm in constants.BASE_PACKAGE_MANAGERS:
                raise UnsupportedFeatureError(f"Package '{pkg.name}' requires '{pkg.pm}' but base PM is '{self.base_pm}'")
            if pkg.pm not in grouped:
                grouped[pkg.pm] = []
            grouped[pkg.pm].append(pkg.name)
        return grouped
    
    def get_soft_reqs(self, soft_pms: List[str]) -> Tuple[List[Package], Dict[str, str]]:
        """Get base requirements for soft package managers with check commands.
        
        Returns:
            Tuple of (packages, check_commands_dict) where check_commands_dict
            maps soft PM name to its check command for conditional installation.
        """
        reqs = []
        seen = set()
        check_cmds = {}
        
        for pm in soft_pms:
            if pm not in constants.SOFT_PACKAGE_MANAGERS:
                continue
            
            cfg = constants.SOFT_PACKAGE_MANAGERS[pm]
            base_reqs = cfg.get("base_requirements", {})
            req_pkgs = base_reqs.get(self.base_pm, None)
            
            if req_pkgs is None:
                raise UnsupportedFeatureError(f"Soft PM '{pm}' cannot be installed by '{self.base_pm}'")
            
            # Store check command for conditional installation
            check_cmds[pm] = cfg.get("check_cmd", "")
            
            # Collect prerequisite packages (may be empty list)
            for req_name in req_pkgs:
                key = (req_name, self.base_pm)
                if key not in seen and key not in self._installed_prereqs:
                    reqs.append(Package(name=req_name, pm=self.base_pm))
                    seen.add(key)
        
        self._installed_prereqs.update(seen)
        return reqs, check_cmds
    
    def gen_cmds(self, pkgs: List[Package], stage: str = "runtime") -> str:
        """
        Generate install command block.
        
        Args:
            pkgs: List of packages to install
            stage: Stage name ("build" or "runtime")
        
        Returns:
            Multi-line installation commands
        """
        if not pkgs:
            return ""
        
        # Group by PM
        grouped = self.group(pkgs)
        
        # Separate base and soft PMs
        base_grps = {k: v for k, v in grouped.items() 
                     if k in constants.BASE_PACKAGE_MANAGERS}
        soft_grps = {k: v for k, v in grouped.items() 
                     if k in constants.SOFT_PACKAGE_MANAGERS}
        
        cmds = []
        
        # 1. Install soft PM prerequisites first
        if soft_grps:
            soft_pms = list(soft_grps.keys())
            prereqs, check_cmds = self.get_soft_reqs(soft_pms)
            
            if prereqs:
                prereq_grps = self.group(prereqs)
                for pm, names in prereq_grps.items():
                    relevant_checks = [check_cmds[spm] for spm in soft_pms 
                                      if check_cmds.get(spm) and spm in soft_grps]
                    
                    block = self._gen_pm_cmd(
                        pm, names, 
                        f"Install prerequisites for {', '.join(soft_pms)}",
                        checks=relevant_checks
                    )
                    if block:
                        cmds.append(block)
        
        cleanup = stage == "runtime"
        # 2. Install base PM packages
        for pm, names in base_grps.items():
            block = self._gen_pm_cmd(pm, names, f"Install {stage} packages via {pm}", cleanup)
            if block:
                cmds.append(block)
        
        # 3. Install soft PM packages
        for pm, names in soft_grps.items():
            block = self._gen_pm_cmd(pm, names, f"Install {stage} packages via {pm}", cleanup)
            if block:
                cmds.append(block)
        
        return "\n\n".join(cmds)
    
    def _gen_pm_cmd(self, pm: str, names: List[str], comment: str, 
                    do_cleanup: bool = False, checks: List[str] = None) -> str:
        """Generate install command for a specific package manager.
        
        Args:
            pm: Package manager name
            names: List of package names
            comment: Comment to add before the command
            do_cleanup: Whether to add cleanup commands
            checks: Optional list of check commands (e.g., "command -v pip")
            If provided, installation only happens if ANY check fails
        """
        # Get PM config
        cfg = (constants.BASE_PACKAGE_MANAGERS.get(pm) or 
               constants.SOFT_PACKAGE_MANAGERS.get(pm))
        
        if not cfg:
            raise UnsupportedFeatureError(f"Unknown PM: {pm}")
        
        pkg_str = " ".join(names)
        install = cfg["install_cmd"].format(packages=pkg_str)
        cleanup_cmd = cfg.get("cleanup_cmd", "")
        
        # Build command block
        lines = [f"# {comment}"]
        
        # If check conditions provided, wrap installation in conditional
        if checks:
            negated_checks = [f"! ({check})" for check in checks if check]
            
            if negated_checks:
                condition = " && ".join(negated_checks)
                lines.append(f"RUN if {condition}; then \\")
                
                if do_cleanup and cleanup_cmd:
                    lines.append(f"      {install} && \\")
                    lines.append(f"      {cleanup_cmd}; \\")
                else:
                    lines.append(f"      {install}; \\")
                
                lines.append(f"    fi")
                return "\n".join(lines)
        
        # Standard installation without conditions
        if do_cleanup and cleanup_cmd:
            lines.append(f"RUN {install} && \\")
            lines.append(f"    {cleanup_cmd}")
        else:
            lines.append(f"RUN {install}")
        
        return "\n".join(lines)