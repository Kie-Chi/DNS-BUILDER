import inspect
import importlib
from typing import Dict, Type, Tuple, Set, Optional
import logging
import re


from . import constants
from .base import Behavior
from .bases.internal import InternalImage

logger = logging.getLogger(__name__)


class BehaviorRegistry:
    """
    Registry for dynamically discovering and managing behavior classes.
    Uses reflection to automatically find and register behavior implementations.
    """
    
    def __init__(self):
        self._behaviors: Dict[Tuple[str, str], Type[Behavior]] = {}
        self._software_types: Set[str] = set()
        self._behavior_types: Set[str] = set()
        
    def register_behavior(self, software: str, behavior_type: str, behavior_class: Type[Behavior]):
        """
        Manually register a behavior class.
        
        Args:
            software: Software type (e.g., 'bind', 'unbound')
            behavior_type: Behavior type (e.g., 'forward', 'stub', 'master')
            behavior_class: The behavior class to register
        """
        key = (software, behavior_type)
        self._behaviors[key] = behavior_class
        self._software_types.add(software)
        self._behavior_types.add(behavior_type)
        logger.debug(f"Registered behavior: {software}.{behavior_type} -> {behavior_class.__name__}")
    
    def get_behavior_class(self, software: str, behavior_type: str) -> Optional[Type[Behavior]]:
        """
        Get a behavior class by software and behavior type.
        
        Args:
            software: Software type
            behavior_type: Behavior type
            
        Returns:
            The behavior class if found, None otherwise
        """
        return self._behaviors.get((software, behavior_type))
    
    def get_supported_behaviors(self, software: str) -> Set[str]:
        """
        Get all supported behavior types for a given software.
        
        Args:
            software: Software type
            
        Returns:
            Set of supported behavior types
        """
        return {behavior_type for (sw, behavior_type) in self._behaviors.keys() if sw == software}
    
    def get_supported_software(self) -> Set[str]:
        """Get all supported software types."""
        return self._software_types.copy()
    
    def get_all_behavior_types(self) -> Set[str]:
        """Get all available behavior types across all software."""
        return self._behavior_types.copy()
    
    def auto_discover_behaviors(self, package_name: str = "dnsbuilder.bases.behaviors"):
        """
        Automatically discover and register behavior classes from a package.
        
        Args:
            package_name: Package to scan for behavior classes
        """
        try:
            module = importlib.import_module(package_name)
            
            # Get all classes from the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (obj != Behavior and 
                    issubclass(obj, Behavior) and 
                    not inspect.isabstract(obj)):
                    
                    # Extract software and behavior type from class name
                    software, behavior_type = self._extract_behavior_info(name)
                    if software and behavior_type:
                        self.register_behavior(software, behavior_type, obj)
                        
        except ImportError as e:
            logger.warning(f"Could not import {package_name}: {e}")
    
    def _extract_behavior_info(self, class_name: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract software and behavior type from class name.
        Args:
            class_name: Name of the behavior class
            
        Returns:
            Tuple of (software, behavior_type) or (None, None) if not parseable
        """
        if not class_name.endswith('Behavior'):
            return None, None
            
        # Remove 'Behavior' suffix
        base_name = class_name[:-8]        
        for behavior_type in sorted(constants.BEHAVIOR_TYPES, key=len, reverse=True):
            if base_name.endswith(behavior_type):
                software_part = base_name[:-len(behavior_type)]
                if software_part:  # Ensure we have a software part
                    software = software_part.lower()
                    behavior_type_lower = behavior_type.lower()
                    return software, behavior_type_lower
        
        boundaries = [m.start() + 1 for m in re.finditer(r'[a-z][A-Z]', base_name)]
        
        # Try each boundary as a potential split point
        for boundary in reversed(boundaries):  # Try longer software names first
            software_part = base_name[:boundary]
            behavior_part = base_name[boundary:]
            
            if software_part and behavior_part:
                software = software_part.lower()
                behavior_type = behavior_part.lower()
                return software, behavior_type
                
        return None, None


class ImageRegistry:
    """
    Registry for dynamically discovering and managing image classes.
    Uses reflection to automatically find and register image implementations.
    """
    
    def __init__(self):
        self._images: Dict[str, Type[InternalImage]] = {}
        
    def register_image(self, software: str, image_class: Type[InternalImage]):
        """
        Register an image class for a software type.
        
        Args:
            software: Software type (e.g., 'bind', 'unbound')
            image_class: The image class to register
        """
        self._images[software] = image_class
        logger.debug(f"Registered image: {software} -> {image_class.__name__}")
    
    def get_image_class(self, software: str) -> Optional[Type[InternalImage]]:
        """
        Get an image class by software type.
        
        Args:
            software: Software type
            
        Returns:
            The image class if found, None otherwise
        """
        return self._images.get(software)
    
    def get_supported_software(self) -> Set[str]:
        """Get all supported software types."""
        return set(self._images.keys())
    
    def auto_discover_images(self, package_name: str = "dnsbuilder.bases.internal"):
        """
        Automatically discover and register image classes from a package.
        
        Args:
            package_name: Package to scan for image classes
        """
        try:
            module = importlib.import_module(package_name)
            
            # Get all classes from the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if (obj != InternalImage and 
                    issubclass(obj, InternalImage) and 
                    not inspect.isabstract(obj)):
                    
                    # Extract software type from class name
                    software = self._extract_software_info(name)
                    if software:
                        self.register_image(software, obj)
                        
        except ImportError as e:
            logger.warning(f"Could not import {package_name}: {e}")
    
    def _extract_software_info(self, class_name: str) -> Optional[str]:
        """
        Extract software type from class name.

        Args:
            class_name: Name of the image class
            
        Returns:
            Software type or None if not parseable
        """
        if not class_name.endswith('Image'):
            return None
            
        # Remove 'Image' suffix
        base_name = class_name[:-5]
        
        # Convert to lowercase
        return base_name.lower()


# Global registries
behavior_registry = BehaviorRegistry()
image_registry = ImageRegistry()


def initialize_registries():
    """
    Initialize the global registries with auto-discovery.
    This should be called once during application startup.
    """
    logger.debug("Initializing behavior and image registries...")
    
    # Auto-discover behaviors
    behavior_registry.auto_discover_behaviors()
    
    # Auto-discover images  
    image_registry.auto_discover_images()
    
    logger.debug(f"Discovered {len(behavior_registry._behaviors)} behavior implementations")
    logger.debug(f"Discovered {len(image_registry._images)} image implementations")
    logger.debug(f"Supported software types: {behavior_registry.get_supported_software()}")
