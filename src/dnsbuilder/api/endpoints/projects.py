from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List
from ..services.project_service import ProjectService
from ...datacls.messages import (
    ProjectName, ProjectCreationResponse, ConfigUpdateResponse,
    ImageCreateRequest, ImageUpdateRequest, ImageResponse,
    BuildServiceCreateRequest, BuildServiceUpdateRequest, BuildServiceResponse,
    ValidationRequest, ValidationResponse, ExistsResponse, ReferencesResponse,
    OperationResponse
)
from ...config import ConfigModel
from ..deps import get_project_service

router = APIRouter()

@router.get("/projects", response_model=List[str])
def get_all_projects(project_service: ProjectService = Depends(get_project_service)):
    """
        Get all projects
    """
    return project_service.get_all_projects()

@router.post("/projects", response_model=ProjectCreationResponse, status_code=201)
def create_project(project: ProjectName, project_service: ProjectService = Depends(get_project_service)):
    """
        Create a new project
    """
    project_service.create_project(project.name)
    return {"project_name": project.name}

@router.delete("/projects/{project_name}", response_model=OperationResponse)
def delete_project(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Delete a project and all its files
    """
    if project_service.delete_project(project_name):
        return OperationResponse(success=True, message=f"Project '{project_name}' deleted successfully")
    else:
        raise HTTPException(status_code=404, detail="Project not found")

@router.get(
    "/projects/{project_name}/config", 
    response_model=ConfigModel
)
def get_project_config(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get the config of a project
    """
    config = project_service.get_project_config(project_name)
    if not config:
        raise HTTPException(status_code=404, detail="Project or config not found")
    return config

@router.put(
    "/projects/{project_name}/config", 
    response_model=ConfigUpdateResponse
)
def update_project_config(project_name: str, config: ConfigModel, project_service: ProjectService = Depends(get_project_service)):
    """
        Update the config of a project
    """
    if not project_service.update_project_config(project_name, config.model_dump()):
        raise HTTPException(status_code=400, detail="Invalid config data")
    return {}

@router.get(
    "/projects/{project_name}/validate/config", 
    response_model=ValidationResponse
)
def validate_project_config(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Validate the configuration of a project.
    """
    valid, errors = project_service.validate_project_config(project_name)
    return ValidationResponse(valid=valid, errors=errors)

# CRUD Image
@router.post("/projects/{project_name}/images", response_model=OperationResponse, status_code=201)
def add_image(project_name: str, image: ImageCreateRequest, project_service: ProjectService = Depends(get_project_service)):
    """
        Add a new image to the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    image_data = image.model_dump(by_alias=True, exclude_none=True)
    if project_service.add_image(project_name, image_data):
        return {"status": "success", "message": f"Image '{image.name}' added successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to add image. Image name may already exist or data is invalid.")

@router.put("/projects/{project_name}/images/{image_name}", response_model=OperationResponse)
def update_image(project_name: str, image_name: str, image: ImageUpdateRequest, project_service: ProjectService = Depends(get_project_service)):
    """
        Update a specified image in the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not project_service.image_exists(project_name, image_name):
        raise HTTPException(status_code=404, detail="Image not found")
    
    image_data = image.model_dump(by_alias=True, exclude_none=True)
    if project_service.update_image(project_name, image_name, image_data):
        return {"status": "success", "message": f"Image '{image_name}' updated successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to update image. Data may be invalid.")

@router.delete("/projects/{project_name}/images/{image_name}", response_model=OperationResponse)
def delete_image(project_name: str, image_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Delete a specified image from the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project_service.delete_image(project_name, image_name):
        return {"status": "success", "message": f"Image '{image_name}' deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Image not found")

@router.get("/projects/{project_name}/images", response_model=List[dict])
def get_all_images(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get all images from the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    return project_service.get_all_images(project_name)

@router.get("/projects/{project_name}/images/{image_name}", response_model=ImageResponse)
def get_image(project_name: str, image_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get a specified image from the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    image = project_service.get_image(project_name, image_name)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    
    return ImageResponse(**image)

# CRUD Build Service
@router.post("/projects/{project_name}/builds", response_model=OperationResponse, status_code=201)
def add_build_service(project_name: str, build: BuildServiceCreateRequest, project_service: ProjectService = Depends(get_project_service)):
    """
        Add a new build service to the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    build_data = build.model_dump(exclude_none=True)
    service_name = build.name
    if project_service.add_build_service(project_name, service_name, build_data):
        return {"status": "success", "message": f"Build service '{service_name}' added successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to add build service. Service name may already exist or data is invalid.")

@router.put("/projects/{project_name}/builds/{service_name}", response_model=OperationResponse)
def update_build_service(project_name: str, service_name: str, build: BuildServiceUpdateRequest, project_service: ProjectService = Depends(get_project_service)):
    """
        Update a specified build service in the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not project_service.build_service_exists(project_name, service_name):
        raise HTTPException(status_code=404, detail="Build service not found")
    
    build_data = build.model_dump(exclude_none=True)
    if project_service.update_build_service(project_name, service_name, build_data):
        return {"status": "success", "message": f"Build service '{service_name}' updated successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to update build service. Data may be invalid.")

@router.delete("/projects/{project_name}/builds/{service_name}", response_model=OperationResponse)
def delete_build_service(project_name: str, service_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Delete a specified build service from the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project_service.delete_build_service(project_name, service_name):
        return {"status": "success", "message": f"Build service '{service_name}' deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Build service not found")

@router.get("/projects/{project_name}/builds", response_model=dict)
def get_all_builds(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get all build services from the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    return project_service.get_all_builds(project_name)

@router.get("/projects/{project_name}/builds/{service_name}", response_model=BuildServiceResponse)
def get_build_service(project_name: str, service_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get a specified build service from the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    build_service = project_service.get_build_service(project_name, service_name)
    if not build_service:
        raise HTTPException(status_code=404, detail="Build service not found")
    
    return BuildServiceResponse(name=service_name, **build_service)

# CRUD Config Validation
@router.post("/projects/validate/config", response_model=ValidationResponse)
def validate_config(request: ValidationRequest, project_service: ProjectService = Depends(get_project_service)):
    """
        Validate the configuration
    """
    valid, errors = project_service.validate_config(request.config)
    return ValidationResponse(valid=valid, errors=errors)

# CRUD Existence Check
@router.get("/projects/{project_name}/exists/images", response_model=ExistsResponse)
def check_image_exists(project_name: str, name: str = Query(..., description="The image name to check"), project_service: ProjectService = Depends(get_project_service)):
    """
        Check if an image name already exists in the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    exists = project_service.image_exists(project_name, name)
    return ExistsResponse(exists=exists, name=name)

# CRUD Build Service Existence Check    
@router.get("/projects/{project_name}/exists/builds", response_model=ExistsResponse)
def check_build_service_exists(project_name: str, name: str = Query(..., description="The build service name to check"), project_service: ProjectService = Depends(get_project_service)):
    """
        Check if a build service name already exists in the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    exists = project_service.build_service_exists(project_name, name)
    return ExistsResponse(exists=exists, name=name)

# CRUD Reference Lists
@router.get("/projects/{project_name}/refs/images", response_model=ReferencesResponse)
def get_image_references(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get a list of all image names that can be referenced in the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    references = project_service.get_image_references(project_name)
    return ReferencesResponse(references=references)

# CRUD Build Service Reference Lists    
@router.get("/projects/{project_name}/refs/builds", response_model=ReferencesResponse)
def get_build_service_references(project_name: str, project_service: ProjectService = Depends(get_project_service)):
    """
        Get a list of all build service names that can be referenced in the project.
    """
    if not project_service.get_project_config(project_name):
        raise HTTPException(status_code=404, detail="Project not found")
    
    references = project_service.get_build_service_references(project_name)
    return ReferencesResponse(references=references)