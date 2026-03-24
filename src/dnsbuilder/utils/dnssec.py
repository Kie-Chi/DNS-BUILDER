"""
Utilities for handling DNSSEC configuration

Provides helper functions to extract DNSSEC configuration values from build configs,
supporting both legacy boolean format and new structured format with hooks support.
"""

from typing import Union, List, Dict, Any, Tuple, Optional


def get_dnssec_config(build_conf: Dict[str, Any]) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Extract DNSSEC configuration from build config.

    Supports both legacy format (dnssec: true/false) and new format
    (dnssec: {enable: true/false, include: [...], hooks: {...}}).

    Args:
        build_conf: The build configuration dictionary
    """
    dnssec_config = build_conf.get('dnssec', False)

    # Legacy format: boolean value
    if isinstance(dnssec_config, bool):
        return dnssec_config, [], {}

    # New format: dictionary with enable, include, and hooks
    if isinstance(dnssec_config, dict):
        enable = dnssec_config.get('enable', False)
        include = dnssec_config.get('include', [])
        hooks = dnssec_config.get('hooks', {})

        # Normalize include to list
        if isinstance(include, str):
            include = [include] if include else []
        elif not isinstance(include, list):
            include = []

        # Normalize hooks to dict
        if not isinstance(hooks, dict):
            hooks = {}

        return enable, include, hooks

    # Default: disabled
    return False, [], {}


def is_dnssec_enabled(build_conf: Dict[str, Any]) -> bool:
    """
    Check if DNSSEC is enabled in build config.

    Convenience function that only returns the enable status.

    Args:
        build_conf: The build configuration dictionary
    """
    enable, _, _ = get_dnssec_config(build_conf)
    return enable


def get_dnssec_includes(build_conf: Dict[str, Any]) -> List[str]:
    """
    Get list of files to include for DNSSEC records.

    Args:
        build_conf: The build configuration dictionary

    Returns:
        List of files to include for DNSSEC records
    """
    _, include, _ = get_dnssec_config(build_conf)
    return include


def get_dnssec_hooks(build_conf: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get DNSSEC hooks configuration.

    DNSSEC hooks allow injecting custom scripts at specific points during
    the DNSSEC signing process.

    Available hooks:
        - pre: Executed before zone signing, can modify unsigned_content
        - mid: Executed after all zones are signed and key:/ is populated,
               can modify key:/ filesystem (inject fake DS, modify keys)
        - post: Executed after re-signing completes, can modify final
                signed zones in temp:/services/... filesystem

    Args:
        build_conf: The build configuration dictionary
    """
    _, _, hooks = get_dnssec_config(build_conf)
    return hooks


def get_dnssec_hook(build_conf: Dict[str, Any], hook_name: str) -> Optional[str]:
    """
    Get a specific DNSSEC hook script by name.

    Args:
        build_conf: The build configuration dictionary
        hook_name: Name of the hook ('pre', 'mid', 'post')

    Returns:
        Hook script content as string, or None if not found

    Examples:
        >>> get_dnssec_hook({'dnssec': {'hooks': {'pre': 'pass'}}}, 'pre')
        'pass'
        >>> get_dnssec_hook({'dnssec': {'hooks': {'pre': 'pass'}}}, 'nonexistent')
        None
    """
    hooks = get_dnssec_hooks(build_conf)
    return hooks.get(hook_name)
