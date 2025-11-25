"""
DNS Builder Registries

This module contains registry classes for dynamic class discovery and registration.

Dependencies:
- protocols: For Protocol type hints
- abstractions: For abstract base classes used in discovery
"""

from typing import Dict, Type, Set, Optional, Tuple, TypeVar, Generic
from abc import ABC, abstractmethod
import logging

from . import constants
from .protocols import BehaviorProtocol, ImageProtocol, IncluderProtocol
from .abstractions import Behavior, Includer, InternalImage
from .utils import discover_classes, extract_bhv_info, extract_img_info, extract_inc_info, override

logger = logging.getLogger(__name__)

K = TypeVar('K')
V = TypeVar('V')

class Registry(Generic[K, V], ABC):
    """
    An abstract base class for a generic discoverable registry.
    """
    
    # --- Configuration: To be defined by subclasses ---
    package: Optional[str] = None # package to scan
    base_class: Optional[Type] = None # base class to discover
    
    def __init__(self):
        self._registry: Dict[K, V] = {}
        
        if self.package is None or self.base_class is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define class attributes "
                "'package' and 'base_class'."
            )
            
        logger.debug(f"Initialized {self.__class__.__name__}")
        
    def register(self, key: K, value: V):
        self._registry[key] = value
        logger.debug(f"Registered in {self.__class__.__name__}: {key} -> {getattr(value, '__name__', str(value))}")
        
    def get(self, key: K) -> Optional[V]:
        return self._registry.get(key)

    @property
    def registry(self) -> Dict[K, V]:
        return self._registry
        
    @abstractmethod
    def _register_item(self, class_name: str, discovered_class: Type[V]):
        """
        Abstract method: Defines the logic to register a single discovered class.
        This is the primary method subclasses need to implement.
        """
        raise NotImplementedError

    def discover(self):
        """
        Template method to automatically discover and register classes.
        """
        logger.debug(f"Starting discovery for {self.__class__.__name__} in '{self.package}'...")
        from .utils import discover_classes
        discovered = discover_classes(
            self.package, 
            self.base_class, 
            exclude_abstract=True, 
            exclude_base=True
        )
        
        for name, obj in discovered.items():
            self._register_item(name, obj)
            
        logger.debug(f"Discovery for {self.__class__.__name__} finished. Total items: {len(self._registry)}")


class BehaviorRegistry(Registry[Tuple[str, str], Type[BehaviorProtocol]]):
    """
    Registry for dynamically discovering and managing behavior classes.
    Uses reflection to automatically find and register behavior implementations.
    """
    package = "dnsbuilder.bases.behaviors"
    base_class = Behavior

    @override
    def _register_item(self, class_name: str, discovered_class: Type[BehaviorProtocol]):
        software, behavior_type = extract_bhv_info(class_name, constants.BEHAVIOR_TYPES)
        if software and behavior_type:
            key = (software, behavior_type)
            self.register(key, discovered_class)

    def behavior(self, software: str, behavior_type: str) -> Optional[Type[BehaviorProtocol]]:
        return self.get((software, behavior_type))

    def get_supports(self) -> Set[str]:
        """Get all supported software types."""
        return {sw for (sw, _) in self.registry.keys()}

    def get_all_behaviors(self) -> Set[str]:
        """Get all available behavior types across all software."""
        return {b_type for (_, b_type) in self.registry.keys()}

class ImageRegistry(Registry[str, Type[ImageProtocol]]):
    """
    Registry for dynamically discovering and managing image classes.
    Uses reflection to automatically find and register image implementations.
    """
    package = "dnsbuilder.bases.internal"
    base_class = InternalImage
    
    @override
    def _register_item(self, class_name: str, discovered_class: Type[ImageProtocol]):
        software = extract_img_info(class_name)
        if software:
            self.register(software, discovered_class)

    def image(self, software: str) -> Optional[Type[ImageProtocol]]:
        return self.get(software)

    def get_supports(self) -> Set[str]:
        return set(self.registry.keys())


class IncluderRegistry(Registry[str, Type[IncluderProtocol]]):
    """
    Registry for dynamically discovering and managing includer classes.
    Uses reflection to automatically find and register includer implementations.
    """
    package = "dnsbuilder.bases.includers"
    base_class = Includer
    
    @override
    def _register_item(self, class_name: str, discovered_class: Type[IncluderProtocol]):
        software = extract_inc_info(class_name)
        if software:
            self.register(software, discovered_class)

    def includer(self, software: str) -> Optional[Type[IncluderProtocol]]:
        return self.get(software)

    def get_supports(self) -> Set[str]:
        return set(self.registry.keys())


# Global registries
behavior_registry = BehaviorRegistry()
image_registry = ImageRegistry()
includer_registry = IncluderRegistry()


def initialize_registries():
    """
    Initialize the global registries with auto-discovery.
    This should be called once during application startup.
    """
    logger.debug("Initializing behavior, image, and includer registries...")
    
    # Auto-discover behaviors
    behavior_registry.discover()
    
    # Auto-discover images  
    image_registry.discover()
    
    # Auto-discover includers
    includer_registry.discover()
    
    logger.debug(f"Discovered {len(behavior_registry.registry)} behavior implementations")
    logger.debug(f"Discovered {len(image_registry.registry)} image implementations")
    logger.debug(f"Discovered {len(includer_registry.registry)} includer implementations")
    logger.debug(f"Supported software types: {behavior_registry.get_supports()}")
