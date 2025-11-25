from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from ...datacls.messages import ImageTemplateResponse, BuildServiceTemplateResponse, PredefinedBuildTemplate

router = APIRouter()

@router.get("/templates/image", response_model=ImageTemplateResponse)
def get_image_template():
    """
        Get a default JSON template for a new image.
    """
    template = {
        "from": "ubuntu:22.04",
        "software": "bind",
        "version": "9.18.0",
        "dependency": [],
        "util": [],
    }
    return ImageTemplateResponse(template=template)

@router.get("/templates/build", response_model=BuildServiceTemplateResponse)
def get_build_service_template():
    pass

@router.get("/resources/pr_blds", response_model=List[str])
def get_predefined_build_templates():
    pass

@router.get("/resources/pr_blds/{template_name}", response_model=PredefinedBuildTemplate)
def get_predefined_build_template(template_name: str):
    pass