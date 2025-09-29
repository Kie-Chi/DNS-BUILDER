from fastapi import APIRouter, Depends
from typing import List
from ...datacls.messages import IncludeTemplate, SoftwareRule
from ..services.resource_service import ResourceService
from ..deps import get_resource_service

router = APIRouter()

@router.get("/resources/includes", response_model=List[IncludeTemplate])
def get_includes(service: ResourceService = Depends(get_resource_service)):
    return service.get_includes()

@router.get("/resources/software", response_model=List[str])
def get_software(service: ResourceService = Depends(get_resource_service)):
    return service.get_software()

@router.get("/resources/software/{software_name}/rules", response_model=List[SoftwareRule])
def get_software_rules(software_name: str, service: ResourceService = Depends(get_resource_service)):
    return service.get_software_rules(software_name)