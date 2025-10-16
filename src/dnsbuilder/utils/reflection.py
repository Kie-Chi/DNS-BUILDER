import inspect
from typing import Dict, Set, Optional, Any
import logging
from ..registry import behavior_registry, image_registry

logger = logging.getLogger(__name__)


def get_available_behaviors() -> Dict[str, Set[str]]:
    """
    Get all available behaviors organized by software type.
    
    Returns:
        Dictionary mapping software types to sets of behavior types
    """
    result = {}
    for software in behavior_registry.get_supported_software():
        result[software] = behavior_registry.get_supported_behaviors(software)
    return result


def get_available_images() -> Set[str]:
    """
    Get all available image software types.
    
    Returns:
        Set of supported software types for images
    """
    return image_registry.get_supported_software()


def validate_behavior_support(software: str, behavior_type: str) -> bool:
    """
    Check if a behavior type is supported for a given software.
    
    Args:
        software: Software type (e.g., 'bind', 'unbound')
        behavior_type: Behavior type (e.g., 'forward', 'stub')
        
    Returns:
        True if supported, False otherwise
    """
    return behavior_registry.get_behavior_class(software, behavior_type) is not None


def validate_image_support(software: str) -> bool:
    """
    Check if an image type is supported for a given software.
    
    Args:
        software: Software type (e.g., 'bind', 'unbound')
        
    Returns:
        True if supported, False otherwise
    """
    return image_registry.get_image_class(software) is not None


def get_behavior_class_info(software: str, behavior_type: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a behavior class.
    
    Args:
        software: Software type
        behavior_type: Behavior type
        
    Returns:
        Dictionary with class information or None if not found
    """
    behavior_class = behavior_registry.get_behavior_class(software, behavior_type)
    if not behavior_class:
        return None
        
    return {
        'class_name': behavior_class.__name__,
        'module': behavior_class.__module__,
        'docstring': behavior_class.__doc__,
        'methods': [name for name, _ in inspect.getmembers(behavior_class, inspect.ismethod)],
        'init_signature': str(inspect.signature(behavior_class.__init__))
    }


def get_image_class_info(software: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about an image class.
    
    Args:
        software: Software type
        
    Returns:
        Dictionary with class information or None if not found
    """
    image_class = image_registry.get_image_class(software)
    if not image_class:
        return None
        
    return {
        'class_name': image_class.__name__,
        'module': image_class.__module__,
        'docstring': image_class.__doc__,
        'methods': [name for name, _ in inspect.getmembers(image_class, inspect.ismethod)],
        'init_signature': str(inspect.signature(image_class.__init__))
    }


def discover_custom_behaviors(package_path: str) -> int:
    """
    Discover and register behaviors from a custom package.
    
    Args:
        package_path: Python package path to scan
        
    Returns:
        Number of behaviors discovered and registered
    """
    initial_count = len(behavior_registry._behaviors)
    behavior_registry.auto_discover_behaviors(package_path)
    return len(behavior_registry._behaviors) - initial_count


def discover_custom_images(package_path: str) -> int:
    """
    Discover and register images from a custom package.
    
    Args:
        package_path: Python package path to scan
        
    Returns:
        Number of images discovered and registered
    """
    initial_count = len(image_registry._images)
    image_registry.auto_discover_images(package_path)
    return len(image_registry._images) - initial_count


def print_registry_status():
    """Print current status of all registries for debugging."""
    logger.debug("=== DNSB Registry Status ===")
    logger.debug(f"Behaviors registered: {len(behavior_registry._behaviors)}")
    logger.debug(f"Images registered: {len(image_registry._images)}")
    
    logger.debug("\nSupported software types:")
    for software in sorted(behavior_registry.get_supported_software()):
        behaviors = behavior_registry.get_supported_behaviors(software)
        logger.debug(f"  {software}: {sorted(behaviors)}")
    
    logger.debug("\nSupported image types:")
    for software in sorted(image_registry.get_supported_software()):
        logger.debug(f"  {software}")


def get_framework_capabilities() -> Dict[str, Any]:
    """
    Get comprehensive information about framework capabilities.
    
    Returns:
        Dictionary with complete framework capability information
    """
    return {
        'behaviors': get_available_behaviors(),
        'images': list(get_available_images()),
        'total_behavior_implementations': len(behavior_registry._behaviors),
        'total_image_implementations': len(image_registry._images),
        'supported_software_types': list(behavior_registry.get_supported_software()),
        'all_behavior_types': list(behavior_registry.get_all_behavior_types())
    }