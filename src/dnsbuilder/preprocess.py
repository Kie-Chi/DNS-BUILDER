import logging
import yaml
from typing import Dict, Any, List, Union
from jinja2 import Environment

from .io.path import DNSBPath
from .io.fs import FileSystem
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
    def __init__(self, raw_config: Dict, config_path: str, fs: FileSystem):
        self.raw_config = raw_config
        self.config_path = config_path
        self.jinja_env = Environment()
        self.fs = fs

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
        # Step 3: Normalize images definition variants and output as dict.
        if 'images' in processed_config:
            processed_config['images'] = self._preprocess_images(processed_config['images'])
        
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
            if 'images' in current_config:
                current_config['images'] = self._preprocess_images(current_config['images'])
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

            abs_path = str(path)

            logger.debug(f"Including and preprocessing config file from '{abs_path}'")
            try:
                content = self.fs.read_text(path)
                included_config_raw = yaml.safe_load(content) or {}
                
                include_preprocessor = Preprocessor(included_config_raw, abs_path, self.fs)
                processed_included_config = include_preprocessor.run()
                
                merged_from_includes = deep_merge(processed_included_config, merged_from_includes)

            except FileNotFoundError:
                raise ConfigFileMissingError(f"Included file not found: {abs_path}")
            except yaml.YAMLError as e:
                raise ConfigParsingError(f"Error parsing included YAML file {abs_path}: {e}")

        if 'builds' in current_config:
            current_config['builds'] = self._preprocess_builds(current_config['builds'])
        if 'images' in current_config:
            current_config['images'] = self._preprocess_images(current_config['images'])

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
        Expands builds from list/dict into a canonical dict using shared logic.
        """
        if isinstance(builds_config, dict):
            # Already in the final format
            return builds_config

        if not isinstance(builds_config, list):
            raise ConfigValidationError(f"'builds' must be a dictionary or a list, but got {type(builds_config).__name__}.")

        expanded = self._expand_named_items(builds_config, target='builds')
        return expanded  # type: ignore[return-value]

    def _preprocess_images(self, images_config: Union[List, Dict]) -> Dict[str, Any]:
        """
        Normalizes images to a canonical dict mapping name -> config.
        Values include explicit 'name' field for downstream compatibility.
        """
        # If it's already a dict, ensure values are dicts and inject name.
        if isinstance(images_config, dict):
            final: Dict[str, Any] = {}
            for name, conf in images_config.items():
                if not isinstance(conf, dict):
                    raise ConfigValidationError(f"Image '{name}' definition must be a dictionary, got {type(conf).__name__}.")
                final[name] = {"name": name, **conf}
            return final

        if not isinstance(images_config, list):
            raise ConfigValidationError(f"'images' must be a dictionary or a list, but got {type(images_config).__name__}.")

        # Expand list forms into a dict
        expanded = self._expand_named_items(images_config, target='images')
        return expanded  # type: ignore[return-value]

    def _expand_named_items(self, items: List[Dict[str, Any]], *, target: str) -> Dict[str, Any]:
        """
        Shared expansion logic for named collections supporting:
        - Comprehension blocks: {'name': <template>, 'for_each': <iterable>, 'template': <conf>}
        - Explicit named dicts: {'name': <name>, ...}
        - Single-key dict shorthand: {<name>: <conf>}

        target determines output shape:
        - 'builds' -> Dict[name, conf]
        - 'images' -> Dict[name, conf]
        """
        if target not in {"builds", "images"}:
            raise ConfigValidationError(f"Invalid target for expansion: {target}")

        final: Dict[str, Any] = {}

        for item in items:
            if isinstance(item, dict) and 'for_each' in item:
                name_template = item.get('name')
                iterator_def = item.get('for_each')
                template_conf = item.get('template')

                if not all([name_template, iterator_def is not None, template_conf]):
                    raise ConfigValidationError(f"Invalid {target[:-1]} comprehension block: {item}. Must contain 'name', 'for_each', and 'template' keys.")

                iterator = self._parse_for_each(iterator_def)
                logger.debug(f"Expanding {target} comprehension for '{name_template}' over {len(iterator)} items...")

                for i, value in enumerate(iterator):
                    context = {'i': i, 'value': value}
                    name_rendered = self.jinja_env.from_string(name_template).render(context)
                    rendered_conf = self._render_template_recursive(template_conf, context)
                    if name_rendered in final:
                        raise ConfigValidationError(f"Duplicate name '{name_rendered}' generated from a {target} comprehension.")
                    final[name_rendered] = rendered_conf

            elif isinstance(item, dict) and 'name' in item:
                name_value = item.get('name')
                conf = {k: v for k, v in item.items() if k != 'name'}
                if name_value in final:
                    raise ConfigValidationError(f"Duplicate name '{name_value}' in {target} definition.")
                final[name_value] = conf

            elif isinstance(item, dict) and len(item) == 1:
                name, conf = next(iter(item.items()))
                if not isinstance(conf, dict):
                    raise ConfigValidationError(f"{target[:-1].capitalize()} '{name}' definition must be a dictionary, got {type(conf).__name__}.")
                if name in final:
                    raise ConfigValidationError(f"Duplicate name '{name}' in {target} definition.")
                    
                final[name] = conf
            else:
                raise ConfigValidationError(f"Invalid item in '{target}' list: {item}. Must be a comprehension block, explicit dict with 'name', or a single-key dict shorthand.")

        return final