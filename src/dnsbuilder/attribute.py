"""
Dynamic attribute loader for constants modification.

This module allows users to override constants from a .dnsbattribute file
located in the working directory.
"""

import logging
import yaml
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class AttributeLoader:
    """Loads and applies dynamic attributes from .dnsbattribute file."""
    
    ATTRIBUTE_FILENAME = ".dnsbattribute"
    @staticmethod
    def load(workdir: Path) -> Dict[str, Any]:
        """
        Load attributes from .dnsbattribute file in the working directory.
        """
        attr_path = workdir / AttributeLoader.ATTRIBUTE_FILENAME
        
        if not attr_path.exists():
            logger.debug(f"[AttributeLoader] No .dnsbattribute file found at {attr_path}")
            return {}
        
        try:
            with open(attr_path, 'r', encoding='utf-8') as f:
                attr_data = yaml.safe_load(f)
            
            if not isinstance(attr_data, dict):
                logger.warning(f"[AttributeLoader] .dnsbattribute file is not a dict, skipping")
                return {}
            
            logger.info(f"[AttributeLoader] Loaded attributes from {attr_path}")
            logger.debug(f"[AttributeLoader] Attributes to override: {list(attr_data.keys())}")
            return attr_data
        
        except yaml.YAMLError as e:
            logger.error(f"[AttributeLoader] Error parsing .dnsbattribute YAML: {e}")
            return {}
        except Exception as e:
            logger.error(f"[AttributeLoader] Error loading .dnsbattribute: {e}")
            return {}
    
    @staticmethod
    def apply(constants_module, attributes: Dict[str, Any]) -> None:
        """
        Apply attribute overrides to the constants module.
        Args:
            constants_module: The constants module to modify
            attributes: Dictionary of attribute overrides
        """
        if not attributes:
            return
        
        for key, value in attributes.items():
            if not hasattr(constants_module, key):
                logger.warning(f"[AttributeLoader] Constant '{key}' does not exist, skipping")
                continue
            
            current_value = getattr(constants_module, key)
            
            if isinstance(current_value, dict) and isinstance(value, dict):
                logger.debug(f"[AttributeLoader] Merging dict constant '{key}'")
                AttributeLoader._merge_dict(current_value, value)
                setattr(constants_module, key, current_value)
            
            elif isinstance(current_value, list) and isinstance(value, list):
                logger.debug(f"[AttributeLoader] Extending list constant '{key}'")
                current_value.extend(value)
            
            else:
                # Replace completely
                logger.debug(f"[AttributeLoader] Replacing constant '{key}'")
                setattr(constants_module, key, value)
            
            logger.info(f"[AttributeLoader] Updated constant '{key}'")
    
    @staticmethod
    def _merge_dict(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """
        Deep merge source dict into target dict.
        
        Args:
            target: Target dictionary to merge into
            source: Source dictionary to merge from
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                AttributeLoader._merge_dict(target[key], value)
            else:
                target[key] = value
