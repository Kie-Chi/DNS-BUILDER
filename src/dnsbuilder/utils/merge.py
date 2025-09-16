import copy
import logging
from typing import Dict, Any, List, Union

logger = logging.getLogger(__name__)


def _normalize_to_dict(data: Union[Dict, List, None]) -> Dict[str, Any]:
    """
    Normalizes a dictionary or a list of "KEY=VALUE" strings into a dictionary.
    Returns an empty dict if data is None.
    """
    if not data:
        return {}
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        normalized_dict = {}
        for item in data:
            if not isinstance(item, str):
                logger.warning(
                    f"Skipping non-string item in list intended for dict normalization: {item}"
                )
                continue
            parts = item.split("=", 1)
            if len(parts) == 2:
                normalized_dict[parts[0]] = parts[1]
            else:
                # Format 'VAR' means value from shell, represented as None in YAML.
                normalized_dict[parts[0]] = None
        return normalized_dict

    # If data is not a dict or list, it cannot be normalized.
    raise TypeError(
        f"Data of type {type(data).__name__} cannot be normalized to a dictionary."
    )


def deep_merge(parent: Dict, child: Dict) -> Dict:
    """
    Recursively merges a child dictionary into a parent dictionary with intelligent
        - Dictionaries are merged recursively.
        - Lists are merged by extending unique items.
        - List/Dict combinations are intelligently normalized to dicts and merged.
        - All other types from the child will overwrite the parent.
    
    """
    merged = copy.deepcopy(parent)
    for key, child_value in child.items():
        if key not in merged:
            merged[key] = child_value
            continue

        parent_value = merged[key]

        # Both are dictionaries
        if isinstance(parent_value, dict) and isinstance(child_value, dict):
            merged[key] = deep_merge(parent_value, child_value)

        # Both are lists
        elif isinstance(parent_value, list) and isinstance(child_value, list):
            parent_set = {str(item) for item in parent_value}
            for item in child_value:
                if str(item) not in parent_set:
                    merged[key].append(item)

        # One is a dict, the other is a list
        elif isinstance(parent_value, (dict, list)) and isinstance(
            child_value, (dict, list)
        ):
            try:
                parent_dict = _normalize_to_dict(parent_value)
                child_dict = _normalize_to_dict(child_value)
                parent_dict.update(child_dict)
                merged[key] = parent_dict
            except TypeError:
                # Normalization failed, fall back to override.
                merged[key] = child_value

        # All other type combinations
        else:
            merged[key] = child_value

    return merged
