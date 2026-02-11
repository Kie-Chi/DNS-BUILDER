"""
Utilities for handling DNSSEC configuration

Provides helper functions to extract DNSSEC configuration values from build configs,
supporting both legacy boolean format and new structured format.
"""

from typing import Union, List, Dict, Any, Tuple


def get_dnssec_config(build_conf: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Extract DNSSEC configuration from build config.
    
    Supports both legacy format (dnssec: true/false) and new format 
    (dnssec: {enable: true/false, include: [...]}).
    
    Args:
        build_conf: The build configuration dictionary
        
    Returns:
        A tuple of (enable, include_files) where:
        - enable: Boolean indicating if DNSSEC is enabled
        - include_files: List of files to include for DNSSEC records
        
    Examples:
        # Legacy format
        >>> config = {'dnssec': True}
        >>> get_dnssec_config(config)
        (True, [])
        
        # New format
        >>> config = {'dnssec': {'enable': True, 'include': 'keys.txt'}}
        >>> get_dnssec_config(config)
        (True, ['keys.txt'])
        
        >>> config = {'dnssec': {'enable': True, 'include': ['keys.txt', 'ds.txt']}}
        >>> get_dnssec_config(config)
        (True, ['keys.txt', 'ds.txt'])
    """
    dnssec_config = build_conf.get('dnssec', False)
    
    # Legacy format: boolean value
    if isinstance(dnssec_config, bool):
        return dnssec_config, []
    
    # New format: dictionary with enable and include
    if isinstance(dnssec_config, dict):
        enable = dnssec_config.get('enable', False)
        include = dnssec_config.get('include', [])
        
        # Normalize include to list
        if isinstance(include, str):
            include = [include] if include else []
        elif not isinstance(include, list):
            include = []
            
        return enable, include
    
    # Default: disabled
    return False, []


def is_dnssec_enabled(build_conf: Dict[str, Any]) -> bool:
    """
    Check if DNSSEC is enabled in build config.
    
    Convenience function that only returns the enable status.
    
    Args:
        build_conf: The build configuration dictionary
        
    Returns:
        Boolean indicating if DNSSEC is enabled
        
    Examples:
        >>> is_dnssec_enabled({'dnssec': True})
        True
        >>> is_dnssec_enabled({'dnssec': {'enable': True}})
        True
        >>> is_dnssec_enabled({'dnssec': False})
        False
    """
    enable, _ = get_dnssec_config(build_conf)
    return enable


def get_dnssec_includes(build_conf: Dict[str, Any]) -> List[str]:
    """
    Get list of files to include for DNSSEC records.
    
    Args:
        build_conf: The build configuration dictionary
        
    Returns:
        List of files to include for DNSSEC records
        
    Examples:
        >>> get_dnssec_includes({'dnssec': {'enable': True, 'include': 'keys.txt'}})
        ['keys.txt']
        >>> get_dnssec_includes({'dnssec': True})
        []
    """
    _, include = get_dnssec_config(build_conf)
    return include
