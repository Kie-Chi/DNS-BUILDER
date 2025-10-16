import hashlib
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Any
import fnmatch

from pydantic import BaseModel, Field
from ..io.path import DNSBPath
from ..io.fs import FileSystem
from ..exceptions import DNSBPathNotFoundError, DNSBNotADirectoryError
import logging

logger = logging.getLogger(__name__)

# exclude all file level difference
ex_serv_keys = [
    "ref",
    "mixins"
    "behavior",
    "files",
    "volumes",
    "mounts",
]
# exclude all serv level difference
ex_proj_keys = [
    "images",
    "builds",
    "include"
]

# Default file patterns to ignore during scanning
DEFAULT_IGNORE_PATTERNS = [
    "*.pcap",
    "*.cache",
    "*.db",
    "*.log",
    "*.tmp", 
    "*.pid",
    "*.lock",
    "*.swp",
    "*.bak",
    "*~",
    "**/__pycache__/**",
    "**/node_modules/**",
    "**/build/**",
    "**/builds/**",
    "**/.git/**",
    ".git/**",
    "**/.git/**",
    "**/logs/**",
    "**/temp/**",
    "**/tmp/**",
    "**/.DS_Store",
    "**/Thumbs.db",
    "**/*.pyc",
    "**/*.pyo",
    "**/.pytest_cache/**",
    "**/.coverage",
    "**/coverage.xml",
    "**/.tox/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.env",
    "**/.env.local",
    "**/.env.*.local"
]



class CacheView(BaseModel, ABC):
    """Abstract base class for cache views"""
    
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    @abstractmethod
    def get_hash(self) -> str:
        """Generate a hash representing the current state (legacy method)"""
        pass
    
    @abstractmethod
    def get_consistency_hash(self) -> str:
        """Generate a hash for consistency checking"""
        pass
    
    @abstractmethod
    def get_update_hash(self) -> str:
        """Generate a hash for update checking"""
        pass
    
    def update_timestamp(self):
        """Update the last modified timestamp"""
        self.updated_at = datetime.now()


class FileCacheView(CacheView):
    """Represents cached metadata for a single file"""
    
    path: str
    content_hash: str
    size: int
    mtime: float  # modification time, no use
    
    def get_hash(self) -> str:
        """Generate hash based on file metadata"""
        return self.get_consistency_hash()
    
    def get_consistency_hash(self) -> str:
        """Generate hash for consistency checking"""
        content = f"{self.path}:{self.content_hash}:{self.size}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_update_hash(self) -> str:
        """Generate hash for update checking"""
        content = f"{self.path}:{self.content_hash}:{self.size}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    @classmethod
    def from_file_path(cls, file_path: DNSBPath, fs: FileSystem) -> "FileCacheView":
        """Create FileCacheView from file path using FileSystem"""
        if not fs.exists(file_path):
            raise DNSBPathNotFoundError(f"File not found: {file_path}")
        
        stat = fs.stat(file_path)
        is_dir = fs.is_dir(file_path)
        
        if is_dir:
            raise DNSBNotADirectoryError(f"Path is a directory, not a file: {file_path}")
        
        # Calculate content hash
        content = fs.read_bytes(file_path)
        content_hash = hashlib.sha256(content).hexdigest()
        
        return cls(
            path=str(file_path),
            size=stat.st_size,
            mtime=stat.st_mtime,
            content_hash=content_hash,
        )
    
    def set_rel_path(self, rel_path: str):
        """Set the relative path for this file cache view"""
        self.path = rel_path


class ServiceCacheView(CacheView):
    """Represents cached metadata for a service"""
    
    name: str
    build_config: Dict[str, Any]
    ip: Optional[str] = None  # Service IP address
    files: Dict[str, FileCacheView] = Field(default_factory=dict)
    
    def get_hash(self) -> str:
        """Generate hash based on service configuration and files"""
        return self.get_consistency_hash()
    
    def get_consistency_hash(self) -> str:
        """Generate hash for consistency checking"""
        files_hash = "".join(sorted([f.get_consistency_hash() for f in self.files.values()]))
        content = f"{self.name}:{files_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_update_hash(self) -> str:
        """Generate hash for update checking"""
        # Get update hashes from all files
        files_hash = "".join(sorted([f.get_update_hash() for f in self.files.values()]))
        filtered_config = {k: v for k, v in self.build_config.items() 
                          if k not in ex_serv_keys}
        config_str = str(sorted(filtered_config.items()))
        
        # Include IP in the hash calculation
        ip_str = self.ip or ""
        content = f"{self.name}:{config_str}:{ip_str}:{files_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def add_file(self, file_view: FileCacheView):
        """Add a file to this service's cache view"""
        self.files[file_view.path] = file_view
        self.update_timestamp()
    
    def remove_file(self, file_path: str):
        """Remove a file from this service's cache view"""
        if file_path in self.files:
            del self.files[file_path]
            self.update_timestamp()
    
    def scan(self, directory: DNSBPath, fs: FileSystem, is_ignore: bool = True, ignore_patterns: Optional[List[str]] = None):
        """Scan and add files from a directory with filtering support
        
        Args:
            directory: Directory to scan
            fs: FileSystem instance
            is_ignore: Whether to ignore files
            ignore_patterns: Custom ignore patterns, if None will use default patterns
        """
        if not fs.exists(directory):
            return
        
        # Use provided patterns or load from .dnsbignore + defaults
        if not is_ignore:
            ignore_patterns = []
        elif ignore_patterns is None:
            ignore_patterns = self._load_ignore_patterns(directory, fs)
        
        for file_path in fs.rglob(directory, "**/*"):
            if fs.is_file(file_path):
                rel_path = str(file_path.relative_to(fs.absolute(directory)))
                
                # Check if file should be ignored
                if self._should_ignore_file(rel_path, ignore_patterns):
                    logger.debug(f"Ignoring file: {rel_path}")
                    continue
                
                try:
                    current_file = FileCacheView.from_file_path(file_path, fs)
                    # Set to relative path for consistent storage
                    current_file.set_rel_path(rel_path)
                    self.files[rel_path] = current_file
                except (DNSBPathNotFoundError, DNSBNotADirectoryError) as e:
                    # Log error but continue processing other files
                    logger.warning(f"Could not process file {file_path}: {e}")
                except UnicodeDecodeError as e:
                    # Skip binary files that can't be decoded as UTF-8
                    logger.debug(f"Skipping binary file {file_path}: {e}")
                except Exception as e:
                    # Log unexpected errors but continue processing
                    logger.warning(f"Unexpected error processing file {file_path}: {e}")
    
    def _should_ignore_file(self, file_path: str, patterns: List[str]) -> bool:
        """Check if a file should be ignored based on patterns
        
        Args:
            file_path: Relative file path to check
            patterns: List of glob patterns to match against
        Returns:
            True if file should be ignored, False otherwise
        """
        normalized_path = file_path.replace('\\', '/')
        
        for pattern in patterns:
            normalized_pattern = pattern.replace('\\', '/')
            if fnmatch.fnmatch(normalized_path, normalized_pattern):
                return True
            if fnmatch.fnmatch(file_path, pattern):
                return True
        
        return False
    
    def _load_ignore_patterns(self, directory: DNSBPath, fs: FileSystem) -> List[str]:
        """Load ignore patterns from .dnsbignore and combine with defaults
        Args:
            directory: Directory to look for .dnsbignore
            fs: FileSystem instance
        Returns:
            Combined list of ignore patterns
        """
        patterns = DEFAULT_IGNORE_PATTERNS.copy()
        
        # Try to load .dnsbignore from the directory
        gitignore_path = directory / ".dnsbignore"
        if fs.exists(gitignore_path):
            try:
                content = fs.read_text(gitignore_path)
                gitignore_patterns = []
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        if line.startswith('/'):
                            gitignore_patterns.append(line[1:])
                        elif line.endswith('/'):
                            # Directory pattern
                            gitignore_patterns.append(f"**/{line}**")
                        else:
                            # File or pattern
                            gitignore_patterns.append(f"**/{line}")
                            gitignore_patterns.append(line)
                
                patterns.extend(gitignore_patterns)
                logger.debug(f"Loaded {len(gitignore_patterns)} patterns from .dnsbignore")
                
            except Exception as e:
                logger.debug(f"Could not read .dnsbignore from {gitignore_path}: {e}")
        
        return patterns


class ProjectCacheView(CacheView):
    """Represents cached metadata for an entire project"""
    
    name: str
    proj_config: Dict[str, Any]
    services: Dict[str, ServiceCacheView] = Field(default_factory=dict)
    docker_compose_hash: Optional[str] = None
    output_dir: str
    
    def get_hash(self) -> str:
        """Generate hash based on project configuration and services"""
        return self.get_consistency_hash()
    
    def get_consistency_hash(self) -> str:
        """Generate hash for consistency checking"""
        services_hash = "".join(sorted([s.get_consistency_hash() for s in self.services.values()]))
        docker_compose_part = f":{self.docker_compose_hash}" if self.docker_compose_hash else ""
        content = f"{self.name}:{services_hash}{docker_compose_part}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_update_hash(self) -> str:
        """Generate hash for update checking"""
        # Get update hashes from all services
        services_hash = "".join(sorted([s.get_update_hash() for s in self.services.values()]))
        
        filtered_config = {k: v for k, v in self.proj_config.items() 
                          if k not in ex_proj_keys}
        config_str = str(sorted(filtered_config.items()))
        # Include filtered project metadata
        content = f"{self.name}:{config_str}:{services_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def add_service(self, service_view: ServiceCacheView):
        """Add a service to this project's cache view"""
        self.services[service_view.name] = service_view
        self.update_timestamp()
    
    def remove_service(self, service_name: str):
        """Remove a service from this project's cache view"""
        if service_name in self.services:
            del self.services[service_name]
            self.update_timestamp()
    
    def get_service(self, service_name: str) -> Optional[ServiceCacheView]:
        """Get a service cache view by name"""
        return self.services.get(service_name)
    
    def has_service_changed(self, service_name: str, current_config: Dict[str, Any]) -> bool:
        """Check if a service configuration has changed"""
        if service_name not in self.services:
            return True  # New service
        
        cached_service = self.services[service_name]
        return cached_service.build_config != current_config
    
    def get_changed_services(self, current_builds: Dict[str, Dict[str, Any]]) -> List[str]:
        """Get list of services that have changed compared to cache"""
        changed = []
        
        # Check for new or modified services
        for service_name, config in current_builds.items():
            if self.has_service_changed(service_name, config):
                changed.append(service_name)
        
        # Check for removed services
        for cached_service in self.services.keys():
            if cached_service not in current_builds:
                changed.append(cached_service)
        
        return changed
    
    def set_docker_compose_hash(self, docker_compose_hash: str):
        """Set the docker-compose file hash"""
        self.docker_compose_hash = docker_compose_hash
        self.update_timestamp()
    
    def calculate_docker_compose_hash(self, docker_compose_path: "DNSBPath", fs: "FileSystem") -> Optional[str]:
        """
        Calculate hash for docker-compose file
        """
        try:
            if not fs.exists(docker_compose_path):
                return None
            
            content = fs.read_bytes(docker_compose_path)
            return hashlib.sha256(content).hexdigest()
            
        except Exception as e:
            logger.error(f"Error calculating docker-compose hash: {e}")
            return None