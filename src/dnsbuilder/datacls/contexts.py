"""
DNS Builder Build Context

This module contains the BuildContext data class, which holds all state
for a build run. It uses Protocol types to avoid circular dependencies.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Dict, Optional, Any

from ..protocols import ImageProtocol, BehaviorFactoryProtocol, IncluderFactoryProtocol
from ..config import Config
from ..io import DNSBPath, FileSystem, AppFileSystem


class BuildContext(BaseModel):
    """
    Holds the shared, immutable state and configuration for a build run.
    
    Uses Protocol types (ImageProtocol, BehaviorFactoryProtocol, etc.) instead of
    concrete types to avoid circular dependencies.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    fs: FileSystem = Field(default_factory=AppFileSystem)

    config: Config
    images: Dict[str, ImageProtocol]
    output_dir: DNSBPath
    
    behavior_factory: Optional[BehaviorFactoryProtocol] = None
    includer_factory: Optional[IncluderFactoryProtocol] = None
    
    resolved_builds: Dict[str, Dict] = Field(default_factory=dict)
    service_ips: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def init_dependent_factories(self) -> "BuildContext":
        """Initialize includer factory if not provided"""
        if self.includer_factory is None:
            from ..factories import IncluderFactory
            object.__setattr__(
                self, "includer_factory", IncluderFactory(fs=self.fs)
            )
        return self

    @model_validator(mode="after")
    def init_behavior_factory(self) -> "BuildContext":
        """Initialize behavior factory if not provided"""
        if self.behavior_factory is None:
            from ..factories import BehaviorFactory
            object.__setattr__(
                self, "behavior_factory", BehaviorFactory()
            )
        return self