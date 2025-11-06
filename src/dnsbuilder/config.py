import yaml
import logging
from typing import Dict, Any, List, Set, Optional, Union
from pydantic import BaseModel, Field, ValidationError, model_validator, ConfigDict
from pydantic.networks import IPv4Network

from .preprocess import Preprocessor
from . import constants
from .io.path import DNSBPath
from .io.fs import FileSystem, AppFileSystem
from .exceptions import (
    CircularDependencyError,
    ImageDefinitionError,
    ReferenceNotFoundError,
    ConfigParsingError,
    ConfigFileMissingError,
    ConfigValidationError,
)


logger = logging.getLogger(__name__)

class AutomationModel(BaseModel):
    """
    Class Config-Validation Model for automation scripts.
    
    Supports setup, modify, and restrict phases with Python or Bash scripts.
    - setup: String or list of strings/dicts (executed serially within service)
    - modify: String or list of strings/dicts (executed serially within service)
    - restrict: String or list of strings/dicts (executed in parallel)
    """
    setup: Union[str, List[Union[str, Dict[str, Any]]]] = Field(default_factory=list)
    modify: Union[str, List[Union[str, Dict[str, Any]]]] = Field(default_factory=list)
    restrict: Union[str, List[Union[str, Dict[str, Any]]]] = Field(default_factory=list)
    model_config = ConfigDict(extra="allow")


class ImageModel(BaseModel):
    """
        Class Config-Validation Model describe `images`
    """
    ref: Optional[str] = None
    software: Optional[str] = None
    version: Optional[str] = None
    from_os: Optional[str] = Field(None, alias='from') # 'from'
    util: List[str] = Field(default_factory=list)
    dependency: List[str] = Field(default_factory=list)
    mirror: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check_ref_or_base_image_fields(self) -> 'ImageModel':
        """ Check ref exists or from/software/version is given"""
        ref_present = self.ref is not None
        base_fields_present = self.software is not None or self.version is not None or self.from_os is not None

        if ref_present and base_fields_present:
            raise ImageDefinitionError("'ref' cannot be used with 'software', 'version', or 'from'.")
        
        if not ref_present and not (self.software and self.version and self.from_os):
            raise ImageDefinitionError("An image without 'ref' must have 'software', 'version', and 'from' keys.")
        
        return self

class BuildModel(BaseModel):
    """
        Class Config-Validation Model describe `builds`
    """
    image: Optional[str] = None
    ref: Optional[str] = None
    address: Optional[str] = None
    behavior: Optional[str] = None
    mixins: List[str] = Field(default_factory=list)
    build: bool = True
    files: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    mounts: List[str] = Field(default_factory=list)
    cap_add: List[str] = Field(default_factory=list)
    auto: Optional[AutomationModel] = Field(default_factory=AutomationModel)
    extra_conf: Optional[str] = None
    # other `docker-compose` config, we won't check
    model_config = ConfigDict(extra="allow")

    @model_validator(mode='after')
    def check_image_or_ref_present(self) -> 'BuildModel':
        """Check if Image is present"""
        if self.image is None and self.ref is None and (self.auto is None or not self.auto.setup) and (self.auto is None or not self.auto.modify):
            raise ImageDefinitionError("Build must have either an 'image' or a 'ref' or an 'auto.setup' or an 'auto.modify' key.")
        
        if self.ref and self.ref.startswith(constants.STD_BUILD_PREFIX) and self.image is None:
            raise ImageDefinitionError(f"A build using a '{constants.STD_BUILD_PREFIX}' reference requires the 'image' key.")
        return self

class ConfigModel(BaseModel):
    """
        Class Config-Validation Model desribe top-level of config
    """
    name: str
    inet: IPv4Network
    images: Dict[str, ImageModel] = Field(default_factory=dict)
    builds: Dict[str, BuildModel]
    include: Optional[Union[str, List[str]]] = None
    auto: Optional[AutomationModel] = Field(default_factory=AutomationModel)
    mirror: Dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(extra="allow")

    @model_validator(mode='after')
    def validate_mirror(self) -> 'ConfigModel':
        """Ensure mirror is a dictionary"""
        for key in self.mirror.keys():
            if any(key in aliases for aliases in constants.MIRRORS.values()):
                continue
            raise ConfigValidationError(f"Invalid mirror key: {key}, must be one of {constants.MIRRORS.values()}.")
        
        return self

    @model_validator(mode='after')
    def validate_image_keys_constraints(self) -> 'ConfigModel':
        """Ensure image dict keys are valid (no colon)."""
        for key in self.images.keys():
            if ":" in key:
                raise ImageDefinitionError(
                    f"Image name cannot contain ':', found in '{key}'."
                )
        return self

    @model_validator(mode='after')
    def validate_cross_references_and_cycles(self) -> 'ConfigModel':
        """Check if ref-chains a circle"""
        images_by_name = self.images
        defined_image_names = set(images_by_name.keys())
        
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def detect_image_cycle(name: str):
            logger.debug(f"[Validation] Checking image '{name}' for cycles...")
            visiting.add(name)
            image_conf = images_by_name[name]
            
            if image_conf.ref and ':' not in image_conf.ref:
                ref_name = image_conf.ref
                # DEBUG: Log the reference being followed
                logger.debug(f"[Validation] Image '{name}' has ref to '{ref_name}'. Following reference.")
                if ref_name not in defined_image_names:
                    raise ReferenceNotFoundError(f"Image '{name}' has a 'ref' to an undefined image: '{ref_name}'.")
                if ref_name in visiting:
                    raise CircularDependencyError(f"Circular dependency in images: '{name}' -> '{ref_name}' forms a loop.")
                if ref_name not in visited:
                    detect_image_cycle(ref_name)
            
            visiting.remove(name)
            visited.add(name)
            logger.debug(f"[Validation] Image '{name}' passed cycle check.")

        logger.debug("Starting image dependency and cycle validation...")
        for name in defined_image_names:
            if name not in visited:
                detect_image_cycle(name)
        logger.debug("Image validation completed successfully.")

        builds_by_name = self.builds
        defined_build_names = set(builds_by_name.keys())
        visiting.clear()
        visited.clear()
        def detect_build_cycle(name: str):
            logger.debug(f"[Validation] Checking build '{name}' for cycles...")
            visiting.add(name)
            build_conf = builds_by_name[name]
            if build_conf.ref and ':' not in build_conf.ref:
                ref_name = build_conf.ref
                logger.debug(f"[Validation] Build '{name}' has ref to '{ref_name}'. Following reference.")
                if ref_name not in defined_build_names:
                    raise ReferenceNotFoundError(f"Build '{name}' has a 'ref' to an undefined build: '{ref_name}'.")
                if ref_name in visiting:
                    raise CircularDependencyError(f"Circular dependency in builds: '{name}' -> '{ref_name}' forms a loop.")
                if ref_name not in visited:
                    detect_build_cycle(ref_name)
            
            visiting.remove(name)
            visited.add(name)
            logger.debug(f"[Validation] Build '{name}' passed cycle check.")

        logger.debug("Starting build dependency and cycle validation...")
        for name in defined_build_names:
            if name not in visited:
                detect_build_cycle(name)
        logger.debug("Build validation completed successfully.")
        
        return self

class Config:
    """
    Loads and validates the config.yml file using Pydantic models.
    It is the sole gatekeeper for configuration.
    """
    def __init__(self, config_path: str, fs: FileSystem = AppFileSystem()):
        self.path = config_path
        self.fs = fs
        logger.info(f"Loading configuration from '{self.path}'...")
        raw_data = self._load_raw_config()

        # preprocess Python-like builds
        preprocessor = Preprocessor(raw_data, self.path, self.fs)
        processed_data = preprocessor.run()
        
        logger.info("Validating configuration structure with Pydantic...")
        try:
            self.model = ConfigModel.model_validate(processed_data)
            logger.debug(f"Configuration model validated successfully: \n{self.model.model_dump_json(indent=2)}")
            logger.info("Configuration validation passed.")
        except ValidationError as e:
            raise ConfigValidationError(f"Configuration validation failed:\n{e}")
        except (CircularDependencyError, ReferenceNotFoundError, ImageDefinitionError) as e:
            raise e

    def _load_raw_config(self) -> Dict[str, Any]:
        try:
            content = self.fs.read_text(DNSBPath(self.path))
            config_data = yaml.safe_load(content)
            if not isinstance(config_data, dict):
                raise ConfigParsingError("Configuration file must be a YAML document containing a dictionary.")
            logger.debug(f"Successfully parsed YAML from '{self.path}'.")
            return config_data
        except FileNotFoundError:
            raise ConfigFileMissingError(f"Configuration file not found at: {self.path}")
        except yaml.YAMLError as e:
            raise ConfigParsingError(f"Error parsing YAML file: {e}")

    @property
    def name(self) -> str: 
        return self.model.name
    
    @property
    def inet(self) -> str: 
        return str(self.model.inet)

    @property
    def images_config(self) -> Dict[str, Dict[str, Any]]: 
        return {name: img.model_dump(by_alias=True, exclude_none=True) for name, img in self.model.images.items()}

    @property
    def builds_config(self) -> Dict[str, Any]: 
        return {name: build.model_dump(exclude_none=True) for name, build in self.model.builds.items()}

    @property
    def mirror(self) -> Dict[str, Any]:
        return self.model.mirror if self.model.mirror else {}
