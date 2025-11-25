import inspect
import importlib
import re
from .util import to_snake, to_pascal
from typing import Dict, Set, Optional, Any, Tuple, List, Type
from abc import ABC
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# GENERIC REFLECTION UTILITIES
# ============================================================================

def discover_classes(
    pkg_name: str,
    base_cls: type,
    exclude_abstract: bool = True,
    exclude_base: bool = True
) -> Dict[str, type]:
    """
    Discover classes extends base from pkg
    
    Args:
        pkg_name: package name (e.g. 'dnsbuilder.bases.behaviors')
        base_cls: base class (e.g. Behavior, InternalImage)
        exclude_abstract: whether to exclude abstract classes
        exclude_base: whether to exclude base class itself
        
    Returns:
        dictionary {class name: class object}
    """
    discovered = {}
    
    try:
        module = importlib.import_module(pkg_name)
        
        # Get all classes from the module
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Skip the base class itself if requested
            if exclude_base and obj == base_cls:
                continue
            
            # Check if it's a subclass of base_cls
            if not issubclass(obj, base_cls):
                continue
            
            # Skip abstract classes if requested
            if exclude_abstract and inspect.isabstract(obj):
                continue
            
            discovered[name] = obj
            
    except ImportError as e:
        logger.warning(f"Could not import {pkg_name}: {e}")
    
    return discovered


def extract_bhv_info(cls_name: str, bhv_types: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract software type and behavior type from class name
    
    Args:
        cls_name: class name (e.g. 'BindForwardBehavior')
        bhv_types: list of supported behavior types (from constants)
        
    Returns:
        (software, behavior_type) or (None, None)
    """
    if not cls_name.endswith('Behavior'):
        return None, None
    
    # Remove 'Behavior' suffix
    base_name = cls_name[:-8]
    
    # Try matching known behavior types first
    for behavior_type in sorted(bhv_types, key=len, reverse=True):
        if base_name.endswith(behavior_type):
            software_part = base_name[:-len(behavior_type)]
            if software_part:  # Ensure we have a software part
                software = to_snake(software_part)
                behavior_type_lower = behavior_type.lower()
                return software, behavior_type_lower
    
    # Fallback: find camelCase boundaries
    logger.warning(f"Failed to extract software and behavior type from {cls_name}")
    boundaries = [m.start() + 1 for m in re.finditer(r'[a-z][A-Z]', base_name)]
    
    # Try each boundary as a potential split point
    for boundary in reversed(boundaries):  # Try longer software names first
        software_part = base_name[:boundary]
        behavior_part = base_name[boundary:]
        
        if software_part and behavior_part:
            software = to_snake(software_part)
            behavior_type = behavior_part.lower()
            return software, behavior_type
    
    return None, None


def extract_img_info(cls_name: str) -> Optional[str]:
    """
    Extract software type from class name
    
    Args:
        cls_name: class name (e.g. 'BindImage')
        
    Returns:
        software type or None
    """
    if not cls_name.endswith('Image'):
        return None
    
    # Remove 'Image' suffix
    base_name = cls_name[:-5]
    
    # Convert to lowercase
    return to_snake(base_name) if base_name else None


def extract_inc_info(cls_name: str) -> Optional[str]:
    """
    Extract software type from class name
    
    Args:
        cls_name: class name (e.g. 'BindIncluder')
        
    Returns:
        software type or None
    """
    if not cls_name.endswith('Includer'):
        return None
    
    # Remove 'Includer' suffix
    base_name = cls_name[:-8]
    
    # Convert to lowercase
    return to_snake(base_name) if base_name else None


def gen_exports(
    ns: dict,
    base_path: str,
    patterns: Optional[List[str]] = None
) -> List[str]:
    """
    Dynamically generate __all__ list for a module
    
    Args:
        ns: module namespace (usually use globals())
        base_path: base module path (e.g. 'dnsbuilder.bases')
        patterns: optional list of class name patterns (e.g. ['Image', 'Behavior'])
        
    Returns:
            sorted list of exported class names
    """
    exports = []
    
    for name, obj in ns.items():
        # Skip private members
        if name.startswith('_'):
            continue
        
        # Must be a class
        if not inspect.isclass(obj):
            continue
        
        # Must be from the specified base module path
        if not hasattr(obj, '__module__') or base_path not in obj.__module__:
            continue
        
        # If patterns specified, check if class name contains any pattern
        if patterns:
            if not any(pattern in name for pattern in patterns):
                continue
        
        exports.append(name)
    
    return sorted(exports)


# ============================================================================
# REGISTRY-BASED REFLECTION UTILITIES
# ============================================================================

# Import registries (deferred to avoid circular dependency)
def _get_registries():
    """Lazy import of registries to avoid circular dependency"""
    from ..registry import behavior_registry, image_registry, includer_registry
    return behavior_registry, image_registry, includer_registry


def get_available_behaviors() -> Dict[str, Set[str]]:
    """
    Get all available behaviors organized by software type.
    
    Returns:
        Dictionary mapping software types to sets of behavior types
    """
    behavior_registry, _, _ = _get_registries()
    result = {}
    for software in behavior_registry.get_supports():
        result[software] = behavior_registry.get_supported_behaviors(software)
    return result


def get_available_images() -> Set[str]:
    """
    Get all available image software types.
    
    Returns:
        Set of supported software types for images
    """
    _, image_registry, _ = _get_registries()
    return image_registry.get_supports()


def validate_behavior_support(software: str, behavior_type: str) -> bool:
    """
    Check if a behavior type is supported for a given software.
    
    Args:
        software: Software type (e.g., 'bind', 'unbound')
        behavior_type: Behavior type (e.g., 'forward', 'stub')
        
    Returns:
        True if supported, False otherwise
    """
    behavior_registry, _, _ = _get_registries()
    return behavior_registry.get(software, behavior_type) is not None


def validate_image_support(software: str) -> bool:
    """
    Check if an image type is supported for a given software.
    
    Args:
        software: Software type (e.g., 'bind', 'unbound')
        
    Returns:
        True if supported, False otherwise
    """
    _, image_registry, _ = _get_registries()
    return image_registry.get(software) is not None


def behavior_info(software: str, behavior_type: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about a behavior class.
    
    Args:
        software: Software type
        behavior_type: Behavior type
        
    Returns:
        Dictionary with class information or None if not found
    """
    behavior_registry, _, _ = _get_registries()
    behavior_class = behavior_registry.get(software, behavior_type)
    if not behavior_class:
        return None
        
    return {
        'class_name': behavior_class.__name__,
        'module': behavior_class.__module__,
        'docstring': behavior_class.__doc__,
        'methods': [name for name, _ in inspect.getmembers(behavior_class, inspect.ismethod)],
        'init_signature': str(inspect.signature(behavior_class.__init__))
    }


def image_info(software: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information about an image class.
    
    Args:
        software: Software type
        
    Returns:
        Dictionary with class information or None if not found
    """
    _, image_registry, _ = _get_registries()
    image_class = image_registry.get(software)
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
    behavior_registry, _, _ = _get_registries()
    initial_count = len(behavior_registry._behaviors)
    behavior_registry.discover_behaviors(package_path)
    return len(behavior_registry._behaviors) - initial_count


def discover_custom_images(package_path: str) -> int:
    """
    Discover and register images from a custom package.
    
    Args:
        package_path: Python package path to scan
        
    Returns:
        Number of images discovered and registered
    """
    _, image_registry, _ = _get_registries()
    initial_count = len(image_registry._images)
    image_registry.discover_images(package_path)
    return len(image_registry._images) - initial_count


def print_registry_status():
    """Print current status of all registries for debugging."""
    behavior_registry, image_registry, _ = _get_registries()
    logger.debug("=== DNSB Registry Status ===")
    logger.debug(f"Behaviors registered: {len(behavior_registry._behaviors)}")
    logger.debug(f"Images registered: {len(image_registry._images)}")
    
    logger.debug("\nSupported software types:")
    for software in sorted(behavior_registry.get_supports()):
        behaviors = behavior_registry.get_supported_behaviors(software)
        logger.debug(f"  {software}: {sorted(behaviors)}")
    
    logger.debug("\nSupported image types:")
    for software in sorted(image_registry.get_supports()):
        logger.debug(f"  {software}")


def get_framework_capabilities() -> Dict[str, Any]:
    """
    Get comprehensive information about framework capabilities.
    
    Returns:
        Dictionary with complete framework capability information
    """
    behavior_registry, image_registry, _ = _get_registries()
    return {
        'behaviors': get_available_behaviors(),
        'images': list(get_available_images()),
        'total_behavior_implementations': len(behavior_registry._behaviors),
        'total_image_implementations': len(image_registry._images),
        'supported_software_types': list(behavior_registry.get_supports()),
        'all_behavior_types': list(behavior_registry.get_all_behaviors())
    }