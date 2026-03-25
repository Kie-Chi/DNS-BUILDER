from typing import Optional, List, Dict, Any
from dnslib import RR
from pydantic import BaseModel, ConfigDict


class VolumeArtifact(BaseModel):
    """
    Represents a file that needs to be generated and mounted as a volume.
    """
    filename: str
    content: str
    container_path: str


class ZoneArtifact(VolumeArtifact):
    """
    Represents a zone file artifact with optional DNSSEC key files.
    Used by ZoneGenerator to return all generated files.
    """
    # For zone files that reference this in config
    is_primary: bool = True  # True for the main zone file to use in config


class BehaviorArtifact(BaseModel):
    """
    Represents output of a behavior generation process.

    Attributes:
        config_line: Configuration content to be placed in a section file
        section: Target section name (e.g., "global", "server", "options").
                 Default is "global" (top-level configuration).
        section_params: Additional parameters for section template formatting.
                        Used when the section template requires parameters
                        (e.g., {"name": "trusted"} for ACL section).
        new_volume: Optional volume artifact (e.g., zone file, hint file)
        new_records: Optional DNS records for Master behavior aggregation
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    config_line: str
    section: str = "global"
    section_params: Dict[str, Any] = {}
    new_volume: Optional[VolumeArtifact] = None
    new_records: Optional[List[RR]] = None


