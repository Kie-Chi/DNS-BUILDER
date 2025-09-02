from typing import NamedTuple, Optional

class VolumeArtifact(NamedTuple):
    """
        Class represents a file that needs to be generated and mounted as a volume.
    """
    filename: str
    content: str
    container_path: str

class BehaviorArtifact(NamedTuple):
    """
        Class represents output of a behavior generation process.
    """
    config_line: str
    new_volume: Optional[VolumeArtifact] = None
    section: str = 'toplevel'
