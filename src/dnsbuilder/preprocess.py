import logging
import yaml
from typing import Dict, Any, List, Union
from jinja2 import Environment

from .utils.path import DNSBPath
from .utils.merge import deep_merge
from .exceptions import (
    ConfigFileMissingError,
    ConfigParsingError,
    ConfigValidationError,
)

logger = logging.getLogger(__name__)


class Preprocessor:
    """
    Recursively processes configurations, handling 'include' directives and expanding build comprehensions.
    """
    def __init__(self, raw_config: Dict, config_path: str):
        self.raw_config = raw_config
        self.config_path = config_path
        self.jinja_env = Environment()

    def run(self) -> Dict:
        """
        Executes all preprocessing steps and returns the processed configuration.
        """
        logger.info(f"Preprocessing configuration from: {self.config_path}")
        
        # Step 1: Handle includes recursively.
        processed_config = self._process_includes()

        # Step 2: Process other directives like 'for_each' on the merged config.
        if 'builds' in processed_config:
            processed_config['builds'] = self._preprocess_builds(processed_config['builds'])
        
        logger.info(f"Finished preprocessing for: {self.config_path}")
        return processed_config

    def _process_includes(self) -> Dict:
        """
        Handles the 'include' directive by recursively preprocessing and merging files.
        """
        current_config = self.raw_config.copy()

        if 'include' not in current_config:
            if 'builds' in current_config:
                current_config['builds'] = self._preprocess_builds(current_config['builds'])
            return current_config

        include_files = current_config.pop('include')
        if not isinstance(include_files, list):
            include_files = [include_files]

        base_dir = DNSBPath(self.config_path).parent
        
        merged_from_includes = {}

        for file_path in include_files:
            path = DNSBPath(file_path)
            if not path.is_absolute() and not path.is_resource:
                path = base_dir / path

            abs_path = str(path) if not path.is_resource else path.origin

            logger.debug(f"Including and preprocessing config file from '{abs_path}'")
            try:
                with path.open('r') as f:
                    included_config_raw = yaml.safe_load(f) or {}
                    
                    include_preprocessor = Preprocessor(included_config_raw, abs_path)
                    processed_included_config = include_preprocessor.run()
                    
                    merged_from_includes = deep_merge(processed_included_config, merged_from_includes)

            except FileNotFoundError:
                raise ConfigFileMissingError(f"Included file not found: {abs_path}")
            except yaml.YAMLError as e:
                raise ConfigParsingError(f"Error parsing included YAML file {abs_path}: {e}")

        if 'builds' in current_config:
            current_config['builds'] = self._preprocess_builds(current_config['builds'])

        # Finally, merge the current config on top of the included configs.
        final_config = deep_merge(merged_from_includes, current_config)
        return final_config

    def _render_template_recursive(self, item: Any, context: Dict) -> Any:
        """Recursively render Jinja2 templates in strings within a data structure."""
        if isinstance(item, str):
            return self.jinja_env.from_string(item).render(context)
        elif isinstance(item, list):
            return [self._render_template_recursive(sub_item, context) for sub_item in item]
        elif isinstance(item, dict):
            return {key: self._render_template_recursive(value, context) for key, value in item.items()}
        else:
            return item

    def _parse_for_each(self, iterator_def: Union[List, Dict]) -> List:
        """Parses the 'for_each' definition"""
        # list like `['a', 'b', 'c']`
        if isinstance(iterator_def, list):
            return iterator_def
        
        # Python-range like `range: range_str`
        if isinstance(iterator_def, dict) and 'range' in iterator_def:
            range_args = iterator_def['range']
            try:
                if isinstance(range_args, int):
                    return list(range(range_args))
                if isinstance(range_args, list):
                    return list(range(*range_args))
            except (TypeError, ValueError) as e:
                raise ConfigValidationError(f"Invalid 'range' arguments in for_each: {range_args}. Must be an int or a list of ints. Error: {e}")
        
        raise ConfigValidationError(f"Invalid 'for_each' format: {iterator_def}. Must be a list or a dict with a 'range' key.")

    def _preprocess_builds(self, builds_config: Union[List, Dict]) -> Dict:
        """
        Expands any list-comprehension style builds into standard build definitions.
        """
        if isinstance(builds_config, dict):
            # Already in the final format, nothing to do.
            return builds_config

        if not isinstance(builds_config, list):
            raise ConfigValidationError(f"'builds' must be a dictionary or a list, but got {type(builds_config).__name__}.")

        final_builds: Dict[str, Any] = {}

        for item in builds_config:
            if isinstance(item, dict) and 'for_each' in item:
                # This is a comprehension block
                name_template = item.get('name')
                iterator_def = item.get('for_each')
                template_conf = item.get('template')

                if not all([name_template, iterator_def is not None, template_conf]):
                    raise ConfigValidationError(f"Invalid build comprehension block: {item}. Must contain 'name', 'for_each', and 'template' keys.")

                iterator = self._parse_for_each(iterator_def)
                logger.debug(f"Expanding build comprehension for '{name_template}' over {len(iterator)} items...")
                
                for i, value in enumerate(iterator):
                    context = {'i': i, 'value': value}
                    # Render the name for the new service
                    service_name = self.jinja_env.from_string(name_template).render(context)
                    
                    if service_name in final_builds:
                        raise ConfigValidationError(f"Duplicate service name '{service_name}' generated from a build comprehension.")
                    final_builds[service_name] = self._render_template_recursive(template_conf, context)
            
            elif isinstance(item, dict) and len(item) == 1:
                final_builds.update(item)
            else:
                raise ConfigValidationError(f"Invalid item in 'builds' list: {item}. Must be a comprehension block or a single-key dictionary for a service.")
        
        return final_builds