from typing import Optional, List
from dnslib import RR
from pydantic import BaseModel, ConfigDict
from .. import constants

class VolumeArtifact(BaseModel):
    """
        Class represents a file that needs to be generated and mounted as a volume.
    """
    filename: str
    content: str
    container_path: str

class BehaviorArtifact(BaseModel):
    """
        Class represents output of a behavior generation process.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    config_line: str
    new_volume: Optional[VolumeArtifact] = None
    section: constants.BehaviorSection = constants.BehaviorSection.TOPLEVEL
    new_records: Optional[List[RR]] = None


