from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class ProjectName(BaseModel):
    name: str

class ProjectCreationResponse(BaseModel):
    status: str = "success"
    project_name: str

class ConfigUpdateResponse(BaseModel):
    status: str = "success"
    message: str = "Configuration saved."

class BuildStartRequest(BaseModel):
    debug: bool = False
    generate_graph: bool = False

class BuildStartResponse(BaseModel):
    build_id: str
    status: str = "started"

class BuildStatusResponse(BaseModel):
    project_name: str
    status: str
    start_time: float
    end_time: Optional[float] = None

class BuildLogsResponse(BaseModel):
    logs: List[str]
    last_index: int

class ArtifactsResponse(BaseModel):
    files: List[str]

class IncludeTemplate(BaseModel):
    name: str
    description: str

class SoftwareRule(BaseModel):
    version: str
    dependency: str | None

#
#
# CRUD Models
#
#


class ImageCreateRequest(BaseModel):
    """
        Create a new image.
    """
    name: str
    ref: Optional[str] = None
    software: Optional[str] = None
    version: Optional[str] = None
    from_os: Optional[str] = Field(None, alias='from')
    util: List[str] = Field(default_factory=list)
    dependency: List[str] = Field(default_factory=list)
    mirror: Dict[str, Any] = Field(default_factory=dict)

class ImageUpdateRequest(BaseModel):
    """
        Update an existing image.
    """
    ref: Optional[str] = None
    software: Optional[str] = None
    version: Optional[str] = None
    from_os: Optional[str] = Field(None, alias='from')
    util: List[str] = Field(default_factory=list)
    dependency: List[str] = Field(default_factory=list)
    mirror: Dict[str, Any] = Field(default_factory=dict)

class ImageResponse(BaseModel):
    """
        Response model for image operations.
    """
    name: str
    ref: Optional[str] = None
    software: Optional[str] = None
    version: Optional[str] = None
    from_os: Optional[str] = Field(None, alias='from')
    util: List[str] = Field(default_factory=list)
    dependency: List[str] = Field(default_factory=list)
    mirror: Dict[str, Any] = Field(default_factory=dict)

# 
class BuildServiceCreateRequest(BaseModel):
    """
        Create a new build service.
    """
    name: str
    image: Optional[str] = None
    ref: Optional[str] = None
    address: Optional[str] = None
    behavior: Optional[str] = None
    mixins: List[str] = Field(default_factory=list)
    build: bool = True
    files: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    mounts: List[str] = Field(default_factory=list)
    cap_add: List[str] = Field(default_factory=list)

class BuildServiceUpdateRequest(BaseModel):
    """
        Update an existing build service.
    """
    image: Optional[str] = None
    ref: Optional[str] = None
    address: Optional[str] = None
    behavior: Optional[str] = None
    mixins: List[str] = Field(default_factory=list)
    build: bool = True
    files: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    mounts: List[str] = Field(default_factory=list)
    cap_add: List[str] = Field(default_factory=list)

class BuildServiceResponse(BaseModel):
    """
        Response model for build service operations.
    """
    name: str
    image: Optional[str] = None
    ref: Optional[str] = None
    address: Optional[str] = None
    behavior: Optional[str] = None
    mixins: List[str] = Field(default_factory=list)
    build: bool = True
    files: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    mounts: List[str] = Field(default_factory=list)
    cap_add: List[str] = Field(default_factory=list)

# 
#
# Template Models
#
#

class ImageTemplateResponse(BaseModel):
    """
        Response model for image template operations.
    """
    name: str
    ref: Optional[str] = None
    software: Optional[str] = None
    version: Optional[str] = None
    from_os: Optional[str] = Field(None, alias='from')
    util: List[str] = Field(default_factory=list)
    dependency: List[str] = Field(default_factory=list)
    mirror: Dict[str, Any] = Field(default_factory=dict)

class BuildServiceTemplateResponse(BaseModel):
    """
        Response model for build service template operations.
    """
    name: str
    image: Optional[str] = None
    ref: Optional[str] = None
    address: Optional[str] = None
    behavior: Optional[str] = None
    mixins: List[str] = Field(default_factory=list)
    build: bool = True
    files: Dict[str, str] = Field(default_factory=dict)
    volumes: List[str] = Field(default_factory=list)
    mounts: List[str] = Field(default_factory=list)
    cap_add: List[str] = Field(default_factory=list)

class PredefinedBuildTemplate(BaseModel):
    """
        Predefined build template.
    """
    name: str
    description: str
    template: Dict[str, Any]

# 
#
# Validation Models
#
#

class ValidationRequest(BaseModel):
    """
        Request model for validation.
    """
    config: Dict[str, Any]

class ValidationResponse(BaseModel):
    """
        Response model for validation.
    """
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class ExistsResponse(BaseModel):
    """
        Response model for existence check.
    """
    exists: bool
    name: str

class ReferencesResponse(BaseModel):
    references: List[str]

# 
#
# Operation Models
#
#

class OperationResponse(BaseModel):
    """
        Response model for operation status.
    """
    status: str = "success"
    message: str = ""