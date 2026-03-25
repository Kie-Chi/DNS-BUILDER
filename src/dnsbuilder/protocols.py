"""
DNS Builder Protocol Definitions

This module contains all Protocol definitions for the DNSBuilder framework.

Protocols are the foundation layer with zero dependencies on other dnsbuilder modules.
"""

from typing import Protocol, Dict, Any, List, Optional, Type, Set, runtime_checkable
from . import constants


# ============================================================================
# Image Protocols
# ============================================================================

@runtime_checkable
class ImageProtocol(Protocol):
    """
    Protocol for all image types (internal and external).
    
    Images represent Docker image configurations that can be built or referenced.
    """
    
    name: str
    ref: Optional[str]
    
    def write(self, directory: Any) -> None:
        """
        Write image artifacts (e.g., Dockerfile) to the specified directory.
        
        Args:
            directory: Target directory path
        """
        ...
    
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge parent image configuration with child configuration.
        
        Args:
            child_config: Child image configuration
            
        Returns:
            Merged configuration dictionary
        """
        ...


# ============================================================================
# Behavior Protocols
# ============================================================================

@runtime_checkable
class BehaviorProtocol(Protocol):
    """
    Protocol for DNS behavior implementations.
    
    Behaviors define how DNS servers handle different zones and queries.
    """
    
    zone: str
    targets: List[str]
    
    def generate(self, service_name: str, build_context: Any) -> Any:
        """
        Generate behavior artifacts (config lines, files, etc.).
        
        Args:
            service_name: Name of the service this behavior is for
            build_context: Current build context containing all build information
            
        Returns:
            BehaviorArtifact containing generated configuration
        """
        ...


# ============================================================================
# Includer Protocols
# ============================================================================

@runtime_checkable
class IncluderProtocol(Protocol):
    """
    Protocol for configuration file assemblers.

    Includers handle the assembly of ConfigFragments into main configuration files
    for different DNS software. They work as delayed-binding configuration assemblers:
    1. Collect ConfigFragments via add()
    2. Assemble them at the end via assemble()
    """

    def add(self, fragment: Any) -> None:
        """
        Register a ConfigFragment for later assembly.

        Args:
            fragment: ConfigFragment instance with section, src, dst info
        """
        ...

    def assemble(self) -> None:
        """
        Assemble all pending fragments into main configs.

        This is the core method that performs the final configuration merge.
        Called at the end of the configuration generation process.
        """
        ...


# ============================================================================
# Factory Protocols
# ============================================================================

@runtime_checkable
class ImageFactoryProtocol(Protocol):
    """
    Protocol for image factory implementations.
    
    Factories are responsible for creating and resolving image instances.
    """
    
    def create_all(self) -> Dict[str, ImageProtocol]:
        """
        Create all defined images, resolving their references.
        
        Returns:
            Dictionary mapping image names to image instances
        """
        ...


@runtime_checkable
class BehaviorFactoryProtocol(Protocol):
    """
    Protocol for behavior factory implementations.
    
    Factories create appropriate behavior instances based on configuration.
    """
    
    def create(self, line: str, software_type: str) -> BehaviorProtocol:
        """
        Parse a behavior line and return the correct Behavior instance.
        
        Args:
            line: Behavior configuration line (e.g., ". forward root-server")
            software_type: DNS software type (e.g., "bind", "unbound")
            
        Returns:
            Behavior instance
        """
        ...


@runtime_checkable
class IncluderFactoryProtocol(Protocol):
    """
    Protocol for includer factory implementations.

    Factories create appropriate includer instances for different DNS software.

    New Architecture:
    -----------------
    The factory creates Includer instances that are ready for fragment registration.
    Fragments are registered via add() and assembled via assemble().
    """

    def create(self, software_type: str, fragments: Any = None) -> IncluderProtocol:
        """
        Create an includer instance for the specified software type.

        Args:
            software_type: DNS software type (e.g., "bind", "unbound")
            fragments: Optional list of ConfigFragments to register immediately

        Returns:
            Includer instance ready for fragment registration
        """
        ...


# ============================================================================
# Registry Protocols
# ============================================================================

@runtime_checkable
class BehaviorRegistryProtocol(Protocol):
    """
    Protocol for behavior registries.
    
    Registries manage discovery and registration of behavior implementations.
    """
    
    def register(self, software: str, behavior_type: str, behavior_class: Any) -> None:
        """Register a behavior class."""
        ...
    
    def behavior(self, software: str, behavior_type: str) -> Optional[Any]:
        """Get a behavior class by software and type."""
        ...


@runtime_checkable
class ImageRegistryProtocol(Protocol):
    """
    Protocol for image registries.
    
    Registries manage discovery and registration of image implementations.
    """
    
    def register(self, software: str, image_class: Any) -> None:
        """Register an image class."""
        ...
    
    def image(self, software: str) -> Optional[Any]:
        """Get an image class by software type."""
        ...


@runtime_checkable
class IncluderRegistryProtocol(Protocol):
    """
    Protocol for includer registries.

    Registries manage discovery and registration of includer implementations.
    """

    def register(self, software: str, includer_class: Any) -> None:
        """Register an includer class."""
        ...

    def includer(self, software: str) -> Optional[Any]:
        """Get an includer class by software type."""
        ...


# ============================================================================
# Zone Generator Protocols
# ============================================================================

@runtime_checkable
class ZoneGeneratorProtocol(Protocol):
    """
    Protocol for zone file generator implementations.

    Zone generators create zone file artifacts for different DNS software.
    Different DNS software may require different zone file formats.
    """

    def generate(self) -> List[Any]:
        """
        Generate zone file artifacts.

        Returns:
            List of ZoneArtifact objects containing zone file content and metadata
        """
        ...


@runtime_checkable
class ZoneGeneratorRegistryProtocol(Protocol):
    """
    Protocol for zone generator registries.

    Registries manage discovery and registration of zone generator implementations.
    """

    def register(self, software: str, generator_class: Type[ZoneGeneratorProtocol]) -> None:
        """Register a zone generator class."""
        ...

    def get(self, software: str) -> Optional[Type[ZoneGeneratorProtocol]]:
        """Get a zone generator class by software type."""
        ...


# ============================================================================
# Section Protocols
# ============================================================================

@runtime_checkable
class SectionProtocol(Protocol):
    """
    Protocol for DNS software configuration section definitions.

    Sections define the configuration blocks supported by each DNS software,
    including formatting templates and file naming conventions.
    """

    @classmethod
    def get_sections(cls) -> Dict[str, Any]:
        """Return all supported configuration sections."""
        ...

    @classmethod
    def get_section(cls, name: str) -> Optional[Any]:
        """Get a specific section by name."""
        ...

    @classmethod
    def get_section_names(cls) -> Set[str]:
        """Get all supported section names."""
        ...

    @classmethod
    def has_section(cls, name: str) -> bool:
        """Check if a section is supported."""
        ...
    
    @classmethod
    def is_repeatable(cls, name: str) -> bool:
        """Check if a section is repeatable."""
        ...

    @classmethod
    def get_filename(cls, section: str, base_name: str = constants.GENERATED_ZONES_FILENAME) -> str:
        """Generate filename for a specific section."""
        ...

    @classmethod
    def format(cls, section: str, content: str, **kwargs) -> str:
        """Format content for a specific section."""
        ...

    @classmethod
    def get_software(cls) -> str:
        """Get the software name for this Section class."""
        ...


@runtime_checkable
class SectionRegistryProtocol(Protocol):
    """
    Protocol for section registries.

    Registries manage registration of section definitions for different DNS software.
    """

    def register(self, software: str, section_class: Type[SectionProtocol]) -> None:
        """Register a section class for a software type."""
        ...

    def get(self, software: str) -> Optional[Type[SectionProtocol]]:
        """Get a section class by software type."""
        ...

    def get_supports(self) -> Set[str]:
        """Get all software types with registered sections."""
        ...

