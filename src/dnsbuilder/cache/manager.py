import json
import hashlib
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic.networks import IPv4Network

from .view import ProjectCacheView, ServiceCacheView, FileCacheView
from ..io.path import DNSBPath
from ..io.fs import FileSystem

logger = logging.getLogger(__name__)


class CacheManager:
    """Cache manager for DNS-Builder"""
    
    def __init__(self, fs: FileSystem, cache_dir: DNSBPath = DNSBPath(".dnsb_cache")):
        """
        Initialize cache manager
        
        Args:
            fs: File system instance
            cache_dir: Cache directory path
        """
        self.fs = fs
        self.cache_dir = cache_dir
        self._ensure_cache_dir()
        
    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        if not self.fs.exists(self.cache_dir):
            self.fs.mkdir(self.cache_dir, parents=True, exist_ok=True)
            logger.debug(f"Created cache directory: {self.cache_dir}")
    
    def _get_project_cache_path(self, project_name: str) -> DNSBPath:
        """Get path to project cache file"""
        return self.cache_dir / f"{project_name}.cache.json"
    
    def save_project_cache(self, project_cache: ProjectCacheView) -> bool:
        """
        Save project cache to file
        
        Args:
            project_cache: Project cache view
            
        Returns:
            bool: Whether save is successful
        """
        try:
            cache_path = self._get_project_cache_path(project_cache.name)
            cache_data = project_cache.model_dump(by_alias=True, exclude_none=True)
            
            # serialize datetime objects
            cache_data = self._serialize_datetime(cache_data)
            
            self.fs.write_text(cache_path, json.dumps(cache_data, indent=2, ensure_ascii=False))
            logger.info(f"Saved project cache for '{project_cache.name}' to {cache_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save project cache for '{project_cache.name}': {e}")
            return False
    
    def load_project_cache(self, project_name: str) -> Optional[ProjectCacheView]:
        """
        Load project cache from file
        
        Args:
            project_name: Project name
            
        Returns:
            Optional[ProjectCacheView]: Project cache view if exists, else None
        """
        try:
            cache_path = self._get_project_cache_path(project_name)
            
            if not self.fs.exists(cache_path):
                logger.debug(f"No cache file found for project '{project_name}'")
                return None
            
            cache_data = json.loads(self.fs.read_text(cache_path))
            
            # deserialize datetime objects
            cache_data = self._deserialize_datetime(cache_data)
            
            return ProjectCacheView(**cache_data)
            
        except Exception as e:
            logger.error(f"Failed to load project cache for '{project_name}': {e}")
            return None
    
    def delete_project_cache(self, project_name: str) -> bool:
        """
        Delete project cache file
        
        Args:
            project_name: Project name
            
        Returns:
            bool: Whether delete is successful
        """
        try:
            cache_path = self._get_project_cache_path(project_name)
            
            if self.fs.exists(cache_path):
                self.fs.remove(cache_path)
                logger.info(f"Deleted project cache for '{project_name}'")
                return True
            else:
                logger.debug(f"No cache file to delete for project '{project_name}'")
                return True
                
        except Exception as e:
            logger.error(f"Failed to delete project cache for '{project_name}': {e}")
            return False
    
    def check_project_consistency(self, project_cache: ProjectCacheView, output_dir: DNSBPath) -> bool:
        """
        Check project cache consistency with output directory
        
        Args:
            project_cache: Project cache view
            output_dir: Output directory path
            
        Returns:
            bool: Whether consistent
        """
        try:
            if not self.fs.exists(output_dir):
                logger.debug(f"Output directory does not exist: {output_dir}")
                return False
            
            # Check docker-compose file consistency
            docker_compose_path = output_dir / "docker-compose.yml"
            if self.fs.exists(docker_compose_path):
                current_compose_hash = self._calculate_file_hash(docker_compose_path)
                if project_cache.docker_compose_hash != current_compose_hash:
                    logger.debug("Docker-compose file hash mismatch")
                    return False
            elif project_cache.docker_compose_hash is not None:
                logger.debug("Docker-compose file missing but expected")
                return False
            
            # Check each service consistency
            for service_name, service_cache in project_cache.services.items():
                service_dir = output_dir / service_name
                if not self._check_service_consistency(service_cache, service_dir):
                    logger.debug(f"Service '{service_name}' consistency check failed")
                    return False
            
            logger.info(f"Project '{project_cache.name}' consistency check passed")
            return True
            
        except Exception as e:
            logger.error(f"Error during project consistency check: {e}")
            return False
    
    def _check_service_consistency(self, service_cache: ServiceCacheView, service_dir: DNSBPath) -> bool:
        """
        Check service cache consistency with service directory
        
        Args:
            service_cache: Service cache view
            service_dir: Service directory path
            
        Returns:
            bool: Whether consistent
        """
        try:
            if not self.fs.exists(service_dir):
                return False
            
            # Check each file consistency
            for file_path, file_cache in service_cache.files.items():
                full_file_path = service_dir / file_path
                
                if not self.fs.exists(full_file_path):
                    logger.debug(f"File missing: {full_file_path}")
                    return False
                
                # Check file consistency hash
                try:
                    current_file_cache = FileCacheView.from_file_path(full_file_path, self.fs)
                    # Set relative path for consistent comparison
                    current_file_cache.set_rel_path(file_path)

                    if current_file_cache.get_consistency_hash() != file_cache.get_consistency_hash():
                        logger.debug(f"File consistency hash mismatch: {full_file_path}")
                        return False
                except Exception as e:
                    logger.debug(f"Error checking file {full_file_path}: {e}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error during service consistency check: {e}")
            return False
    
    def _calculate_file_hash(self, file_path: DNSBPath) -> str:
        """
        Calculate SHA256 hash of a file
        
        Args:
            file_path: File path
            
        Returns:
            str: File hash
        """
        try:
            content = self.fs.read_bytes(file_path)
            return hashlib.sha256(content).hexdigest()
        except Exception as e:
            logger.error(f"Error calculating file hash for {file_path}: {e}")
            return ""
    
    def _serialize_datetime(self, data: Any) -> Any:
        """Recursively serialize datetime and IPv4Network objects to strings"""
        if isinstance(data, datetime):
            return data.isoformat()
        elif isinstance(data, IPv4Network):
            return str(data)
        elif isinstance(data, dict):
            return {k: self._serialize_datetime(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._serialize_datetime(item) for item in data]
        else:
            return data
    
    def _deserialize_datetime(self, data: Any) -> Any:
        """Recursively deserialize strings to datetime objects"""
        if isinstance(data, dict):
            result = {}
            for k, v in data.items():
                if k in ['created_at', 'updated_at'] and isinstance(v, str):
                    try:
                        result[k] = datetime.fromisoformat(v)
                    except ValueError:
                        result[k] = datetime.now()
                else:
                    result[k] = self._deserialize_datetime(v)
            return result
        elif isinstance(data, list):
            return [self._deserialize_datetime(item) for item in data]
        else:
            return data
    
    def list_cached_projects(self) -> List[str]:
        """
        List all cached projects
        
        Returns:
            List[str]: List of project names
        """
        try:
            projects = []
            if self.fs.exists(self.cache_dir):
                for file_path in self.fs.listdir(self.cache_dir):
                    if file_path.name.endswith('.cache.json'):
                        project_name = file_path.name[:-11]  # 移除 '.cache.json'
                        projects.append(project_name)
            return projects
        except Exception as e:
            logger.error(f"Error listing cached projects: {e}")
            return []
    
    def get_cache_stats(self, project_name: str) -> Optional[Dict[str, Any]]:
        """
        Get cache statistics for a project
        
        Args:
            project_name: Project name
            
        Returns:
            Optional[Dict[str, Any]]: Cache statistics
        """
        try:
            project_cache = self.load_project_cache(project_name)
            if not project_cache:
                return None
            
            total_files = sum(len(service.files) for service in project_cache.services.values())
            
            stats = {
                'project_name': project_cache.name,
                'created_at': project_cache.created_at.isoformat(),
                'updated_at': project_cache.updated_at.isoformat(),
                'services_count': len(project_cache.services),
                'total_files': total_files,
                'output_dir': project_cache.output_dir,
                'has_docker_compose': project_cache.docker_compose_hash is not None,
                'services': {
                    name: {
                        'files_count': len(service.files),
                        'created_at': service.created_at.isoformat(),
                        'updated_at': service.updated_at.isoformat()
                    }
                    for name, service in project_cache.services.items()
                }
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting cache stats for '{project_name}': {e}")
            return None