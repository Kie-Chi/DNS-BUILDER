from typing import List, Dict, Any, Optional, Tuple
import yaml
import asyncio
from pydantic import ValidationError

from ...config import Config, ConfigModel, ImageModel, BuildModel
from ...io.path import DNSBPath
from ...io.fs import FileSystem
from ...utils.merge import deep_merge
from ..wsm import manager

class ProjectService:
    def __init__(
        self, fs: FileSystem, workspace: DNSBPath = DNSBPath(".dnsb_cache/workspaces")
    ):
        self.workspace = workspace
        self.fs: FileSystem = fs
        if not self.fs.exists(self.workspace):
            self.fs.mkdir(self.workspace, parents=True, exist_ok=True)

    # General
    def get_all_projects(self) -> List[str]:
        return [d.name for d in self.fs.listdir(self.workspace) if self.fs.is_dir(d)]

    def create_project(self, name: str) -> None:
        project_path = self.workspace / name
        if not self.fs.exists(project_path):
            self.fs.mkdir(project_path, parents=True, exist_ok=True)
            # Create a minimal dnsbuilder.yml
            initial_config = {
                'name': name,
                'inet': '10.88.0.0/16',
                'images': [],
                'builds': {}
            }
            self.fs.write_text(project_path / 'dnsbuilder.yml', yaml.dump(initial_config))
            asyncio.run(manager.broadcast(f"Project '{name}' created."))

    def delete_project(self, name: str) -> bool:
        """Delete the specified project and all its files."""
        try:
            project_path = self.workspace / name
            if not self.fs.exists(project_path):
                return False  # Project does not exist
            
            # Delete the entire project directory
            self.fs.rmtree(project_path)
            asyncio.run(manager.broadcast(f"Project '{name}' deleted."))
            return True
        except Exception:
            return False

    def get_project_config(self, project_name: str):
        config_path = self.workspace / project_name / 'dnsbuilder.yml'
        if not self.fs.exists(config_path):
            return None
        return Config(config_path).model

    def update_project_config(self, project_name: str, config_data: dict):
        config_path = self.workspace / project_name / 'dnsbuilder.yml'
        try:
            # Load existing config to validate against
            existing_config = self.get_project_config(project_name)
            if existing_config:
                # Dict merge with existing config
                merged_config = existing_config.model_dump() | config_data
                ConfigModel.model_validate(merged_config)
            else:
                ConfigModel.model_validate(config_data)
            self.fs.write_text(config_path, yaml.dump(merged_config))
            asyncio.run(manager.broadcast(f"Configuration for project '{project_name}' updated."))
            return True
        except Exception:
            return False

    def validate_project_config(self, project_name: str) -> Tuple[bool, List[str]]:
        try:
            config_data = self.get_project_config(project_name)
            if not config_data:
                return False, ["Configuration file not found."]
            ConfigModel.model_validate(config_data)
            return True, []
        except ValidationError as e:
            return False, e.errors()

    # Images
    def add_image(self, project_name: str, image_data: Dict[str, Any]) -> bool:
        """Add a new image to the project configuration."""
        try:
            ImageModel.model_validate(image_data)

            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return False
            existing_images = config_dict.get('images', [])            
            image_name = image_data.get('name')
            if any(img.get('name') == image_name for img in existing_images):
                return False  # Image name already exists
            
            existing_images.append(image_data)
            config_dict['images'] = existing_images            
            return self._save_config_dict(project_name, config_dict)
        except Exception:
            return False

    def update_image(self, project_name: str, image_name: str, image_data: Dict[str, Any]) -> bool:
        """Update an existing image in the project configuration using dict merge."""
        try:            
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return False
            
            existing_images = config_dict.get('images', [])
            updated = False
            for i, img in enumerate(existing_images):
                if img.get('name') == image_name:
                    merged_image = img | image_data
                    new_name = merged_image.get('name')
                    if new_name != image_name:
                        if any(other_img.get('name') == new_name for j, other_img in enumerate(existing_images) if j != i):
                            return False  # New name already exists
                    try:
                        ImageModel.model_validate(merged_image)
                    except ValidationError:
                        return False  # 合并后的配置无效
                    
                    existing_images[i] = merged_image
                    updated = True
                    break
            
            if not updated:
                return False  # Image does not exist
            
            config_dict['images'] = existing_images
            
            return self._save_config_dict(project_name, config_dict)
        except Exception:
            return False

    def delete_image(self, project_name: str, image_name: str) -> bool:
        """Delete a specified image from the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return False
            
            existing_images = config_dict.get('images', [])
            original_length = len(existing_images)
            existing_images = [img for img in existing_images if img.get('name') != image_name]
            
            if len(existing_images) == original_length:
                return False  # Image does not exist
            
            config_dict['images'] = existing_images
            
            return self._save_config_dict(project_name, config_dict)
        except Exception:
            return False

    def get_all_images(self, project_name: str) -> List[Dict[str, Any]]:
        """Get a list of all images in the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return []
            return config_dict.get('images', [])
        except Exception:
            return []

    def get_image(self, project_name: str, image_name: str) -> Optional[Dict[str, Any]]:
        """Get an existing image from the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return None
            
            existing_images = config_dict.get('images', [])
            for img in existing_images:
                if img.get('name') == image_name:
                    return img
            
            return None
        except Exception:
            return None

    def image_exists(self, project_name: str, image_name: str) -> bool:
        """Check if an image name already exists in the project configuration."""
        return self.get_image(project_name, image_name) is not None

    def get_image_references(self, project_name: str) -> List[str]:
        """Get a list of all image names that can be referenced in the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return []
            
            existing_images = config_dict.get('images', [])
            return [img.get('name') for img in existing_images if img.get('name')]
        except Exception:
            return []

    def add_build_service(self, project_name: str, service_name: str, build_data: Dict[str, Any]) -> bool:
        """Add a new build service to the project configuration."""
        try:
            BuildModel.model_validate(build_data)
            
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return False
            
            existing_builds = config_dict.get('builds', {})
            
            # Check if service name already exists
            if service_name in existing_builds:
                return False  # Service name already exists
            
            existing_builds[service_name] = build_data
            config_dict['builds'] = existing_builds
            
            return self._save_config_dict(project_name, config_dict)
        except Exception:
            return False

    def update_build_service(self, project_name: str, service_name: str, build_data: Dict[str, Any]) -> bool:
        """Update an existing build service in the project configuration using deep merge."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return False
            
            existing_builds = config_dict.get('builds', {})
            if service_name not in existing_builds:
                return False  # Service does not exist
            
            # 使用 dict 合并原有配置和新配置
            merged_build = existing_builds[service_name] | build_data
            
            # 二次检查：验证合并后的构建服务配置是否有效
            try:
                BuildModel.model_validate(merged_build)
            except ValidationError:
                return False  # 合并后的配置无效
            
            existing_builds[service_name] = merged_build
            config_dict['builds'] = existing_builds
            
            return self._save_config_dict(project_name, config_dict)
        except Exception:
            return False

    def delete_build_service(self, project_name: str, service_name: str) -> bool:
        """Delete an existing build service from the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return False
            
            existing_builds = config_dict.get('builds', {})
            if service_name not in existing_builds:
                return False  # Service does not exist
            
            del existing_builds[service_name]
            config_dict['builds'] = existing_builds
            
            return self._save_config_dict(project_name, config_dict)
        except Exception:
            return False

    def get_all_builds(self, project_name: str) -> Dict[str, Dict[str, Any]]:
        """Get a list of all build services in the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return {}
            return config_dict.get('builds', {})
        except Exception:
            return {}

    def get_build_service(self, project_name: str, service_name: str) -> Optional[Dict[str, Any]]:
        """Get an existing build service from the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return None
            
            existing_builds = config_dict.get('builds', {})
            return existing_builds.get(service_name)
        except Exception:
            return None

    def build_service_exists(self, project_name: str, service_name: str) -> bool:
        """Check if a build service name already exists in the project configuration."""
        return self.get_build_service(project_name, service_name) is not None

    def get_build_service_references(self, project_name: str) -> List[str]:
        """Get a list of all build service names that can be referenced in the project configuration."""
        try:
            config_dict = self._load_config_dict(project_name)
            if not config_dict:
                return []
            
            existing_builds = config_dict.get('builds', {})
            return list(existing_builds.keys())
        except Exception:
            return []

    def validate_config(self, config_data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate the configuration data using ConfigModel.

        This method checks for:
        - Unique image names
        - Circular dependencies
        - Existence of referenced images and build services
        - All field validations

        Args:
            config_data (Dict[str, Any]): The configuration data to validate.

        Returns:
            tuple[bool, List[str]]: A tuple containing a boolean indicating
            whether the configuration is valid, and a list of error messages.
        """
        try:
            ConfigModel.model_validate(config_data)
            return True, []
        except ValidationError as e:
            errors = []
            for error in e.errors():
                field = " -> ".join(str(loc) for loc in error["loc"])
                message = error["msg"]
                errors.append(f"{field}: {message}")
            return False, errors
        except Exception as e:
            return False, [str(e)]

    # Helper methods
    def _load_config_dict(self, project_name: str) -> Optional[Dict[str, Any]]:
        """Load the project configuration as a dictionary."""
        config_path = self.workspace / project_name / 'dnsbuilder.yml'
        if not self.fs.exists(config_path):
            return None
        
        try:
            config_text = self.fs.read_text(config_path)
            return yaml.safe_load(config_text)
        except Exception:
            return None

    def _save_config_dict(self, project_name: str, config: Dict[str, Any]) -> bool:
        """保存配置字典到文件"""
        config_path = self.workspace / project_name / 'dnsbuilder.yml'
        try:
            self.fs.write_text(config_path, yaml.dump(config, default_flow_style=False))
            asyncio.run(manager.broadcast(f"Configuration for project '{project_name}' updated."))
            return True
        except Exception:
            return False