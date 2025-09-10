
from pydantic import BaseModel, ConfigDict, Field
from typing import Dict

from ..base import Image
from ..factories import BehaviorFactory, IncluderFactory
from ..config import Config
from ..utils.path import DNSBPath

class BuildContext(BaseModel):
    """
    Holds the shared, immutable state and configuration for a build run.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    config: Config
    images: Dict[str, Image]
    output_dir: DNSBPath
    
    behavior_factory: BehaviorFactory = Field(default_factory=BehaviorFactory)
    includer_factory: IncluderFactory = Field(default_factory=IncluderFactory)
    
    resolved_builds: Dict[str, Dict] = Field(default_factory=dict)
    service_ips: Dict[str, str] = Field(default_factory=dict)