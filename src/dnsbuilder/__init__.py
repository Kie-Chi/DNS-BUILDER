"""
DNSB (DNS Builder) Framework

A flexible DNS configuration management framework with dynamic behavior discovery.

Main modules:
- io: File system and path handling with multi-protocol support
- builder: Core build process and caching
- config: Configuration loading and validation
- cache: Incremental build caching
- bases: Concrete implementations of images, behaviors, and includers
- factories: Factory classes for dynamic object creation
- datacls: Type-safe data classes and models
- auto: Automation scripts support
- utils: Utility functions
- registry: Dynamic class discovery and registration

Quick start example:
```python
import asyncio
from dnsbuilder import Builder, Config, create_app_fs, DNSBPath

fs = create_app_fs()
config = Config("config.yml", fs)
builder = Builder(config, fs=fs)
await builder.run()
```
"""

from .protocols import ImageProtocol, BehaviorProtocol, IncluderProtocol
from .abstractions import Image, Behavior, Includer, InternalImage, ExternalImage, MasterBehavior
from .registry import initialize_registries
from .config import Config, ConfigModel
from .builder import Builder, CachedBuilder
from .io import DNSBPath, FileSystem, AppFileSystem, create_app_fs
from .exceptions import (
    DNSBuilderError,
    ConfigurationError,
    ConfigValidationError,
    BuildError,
    DefinitionError,
)

__version__ = "0.9.0"

__all__ = [
    # Version
    '__version__',
    # Protocols
    'ImageProtocol',
    'BehaviorProtocol',
    'IncluderProtocol',
    # Abstractions
    'Image',
    'Behavior',
    'Includer',
    'InternalImage',
    'ExternalImage',
    # Registry
    'initialize_registries',
    # Config
    'Config',
    'ConfigModel',
    # Builder
    'Builder',
    'CachedBuilder',
    # IO
    'DNSBPath',
    'FileSystem',
    'AppFileSystem',
    'create_app_fs',
    # Exceptions
    'DNSBuilderError',
    'ConfigurationError',
    'ConfigValidationError',
    'BuildError',
    'DefinitionError',
]