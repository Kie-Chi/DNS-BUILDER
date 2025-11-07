"""
DNS Builder Builder Module

- Builder: Standard build process
- CachedBuilder: Incremental build with caching
- ServiceHandler: Individual service artifact generation
- NetworkManager: IP address allocation
- Resolver: Build configuration resolution
- VariableSubstitutor: Variable substitution
- Mapper: Network topology mapping
- GraphGenerator: DOT graph generation

Usage:
    from dnsbuilder.builder import Builder, CachedBuilder
    from dnsbuilder.io import create_app_fs
    
    fs = create_app_fs()
    config = Config("config.yml", fs)
    builder = Builder(config, fs=fs)
    await builder.run()
"""

from .build import Builder
from .cached_builder import CachedBuilder
from .service import ServiceHandler
from .net import NetworkManager
from .resolve import Resolver
from .substitute import VariableSubstitutor
from .map import Mapper, GraphGenerator

__all__ = [
    'Builder',
    'CachedBuilder',
    'ServiceHandler',
    'NetworkManager',
    'Resolver',
    'VariableSubstitutor',
    'Mapper',
    'GraphGenerator',
]