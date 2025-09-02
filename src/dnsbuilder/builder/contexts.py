
from pydantic import BaseModel, ConfigDict, Field
from typing import Dict
from pathlib import Path

from ..images.image import Image
from .behaviors import BehaviorFactory
from .includers import IncluderFactory
from ..config import Config

class BuildContext(BaseModel):
    """
    Holds the shared, immutable state and configuration for a build run.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    config: Config
    images: Dict[str, Image]
    output_dir: Path
    
    behavior_factory: BehaviorFactory = Field(default_factory=BehaviorFactory)
    includer_factory: IncluderFactory = Field(default_factory=IncluderFactory)
    
    resolved_builds: Dict[str, Dict] = Field(default_factory=dict)
    service_ips: Dict[str, str] = Field(default_factory=dict)