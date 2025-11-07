"""
DNS Builder Protocol Definitions

This module contains all Protocol definitions for the DNSBuilder framework.

Protocols are the foundation layer with zero dependencies on other dnsbuilder modules.
"""

from typing import Protocol, Dict, Any, List, Optional, runtime_checkable


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
    Protocol for configuration file includers.
    
    Includers handle including configuration snippets into main config files
    for different DNS software.
    """
    
    def include(self, pair: Any) -> None:
        """
        Write include directive for a configuration file.
        
        Args:
            pair: Volume pair to include (source and destination)
        """
        ...
    
    def contain(self) -> None:
        """
        Contain block-specific config in global main config.
        
        Sets up the structure for including configuration blocks.
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
    """
    
    def create(self, confs: Dict[str, Any], software_type: str) -> IncluderProtocol:
        """
        Create an includer instance for the specified software type.
        
        Args:
            confs: Configuration file paths dictionary
            software_type: DNS software type (e.g., "bind", "unbound")
            
        Returns:
            Includer instance
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
    
    def register_behavior(self, software: str, behavior_type: str, behavior_class: Any) -> None:
        """Register a behavior class."""
        ...
    
    def get_behavior_class(self, software: str, behavior_type: str) -> Optional[Any]:
        """Get a behavior class by software and type."""
        ...


@runtime_checkable
class ImageRegistryProtocol(Protocol):
    """
    Protocol for image registries.
    
    Registries manage discovery and registration of image implementations.
    """
    
    def register_image(self, software: str, image_class: Any) -> None:
        """Register an image class."""
        ...
    
    def get_image_class(self, software: str) -> Optional[Any]:
        """Get an image class by software type."""
        ...


@runtime_checkable
class IncluderRegistryProtocol(Protocol):
    """
    Protocol for includer registries.
    
    Registries manage discovery and registration of includer implementations.
    """
    
    def register_includer(self, software: str, includer_class: Any) -> None:
        """Register an includer class."""
        ...
    
    def get_includer_class(self, software: str) -> Optional[Any]:
        """Get an includer class by software type."""
        ...

