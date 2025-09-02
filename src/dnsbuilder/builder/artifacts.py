from typing import Optional, Literal, Final
from pydantic import BaseModel
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
    config_line: str
    new_volume: Optional[VolumeArtifact] = None
    section: constants.BehaviorSection = constants.BehaviorSection.TOPLEVEL
