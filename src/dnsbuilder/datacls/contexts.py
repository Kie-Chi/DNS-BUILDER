
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Dict, Optional

from ..base import Image
from ..factories import BehaviorFactory, IncluderFactory
from ..config import Config
from ..io.path import DNSBPath
from ..io.fs import FileSystem, AppFileSystem

class BuildContext(BaseModel):
    """
    Holds the shared, immutable state and configuration for a build run.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    fs: FileSystem = Field(default_factory=AppFileSystem)

    config: Config
    images: Dict[str, Image]
    output_dir: DNSBPath
    
    behavior_factory: BehaviorFactory = Field(default_factory=BehaviorFactory)
    includer_factory: Optional[IncluderFactory] = None
    
    resolved_builds: Dict[str, Dict] = Field(default_factory=dict)
    service_ips: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def init_dependent_factories(self) -> "BuildContext":
        if self.includer_factory is None:
            object.__setattr__(
                self, "includer_factory", IncluderFactory(fs=self.fs)
            )
        return self