from importlib import resources
import tempfile
import atexit
import shutil
import logging
from typing import override
from pathlib import Path, PurePosixPath, PureWindowsPath

from ..exceptions import VolumeNotFoundError
from .. import constants

# This temporary directory will persist for the life of the program
# and be cleaned up automatically on exit.
_temp_dir = tempfile.TemporaryDirectory()
atexit.register(_temp_dir.cleanup)

logger = logging.getLogger(__name__)

class DNSBPath(Path):
    """
    A Path subclass for DNS Builder that transparently handles both standard
    file system paths and internal package resources (e.g., 'resource:file.conf').
    """
    # __new__ can be simplified or removed. We keep it to ensure
    # the correct platform-specific Path class (PosixPath/WindowsPath) is used.
    def __new__(cls, *args, **kwargs):
        # Let the parent Path class handle the platform-specific instantiation
        return super().__new__(cls, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        if not args:
            # Handle empty call like Path()
            super().__init__(*args, **kwargs)
            self.is_resource = False
            self.original_path_str = ""
            return

        original_path_str = str(args[0])
        self.original_path_str = original_path_str
        
        # Check if the path is a resource
        if original_path_str.startswith(constants.RESOURCE_PREFIX):
            self.is_resource = True
            logger.debug(f"DNSBPath resolving resource: {original_path_str}")
            resolved_path = self._resolve_resource_to_temp_path(original_path_str)
            logger.debug(f"DNSBPath resolved to temporary path: {resolved_path}")
            
            super().__init__(resolved_path, **kwargs)

        else:
            self.is_resource = False
            logger.debug(f"DNSBPath created for path: {original_path_str}")
            super().__init__(*args, **kwargs)

    @staticmethod
    def _resolve_resource_to_temp_path(resource_str: str) -> Path:
        resource_name = resource_str[len(constants.RESOURCE_PREFIX):]
        try:
            # This logic looks fine.
            if resource_name.startswith('/'):
                traversable = resources.files('dnsbuilder.resources').joinpath(resource_name.lstrip('/'))
            else:
                traversable = resources.files('dnsbuilder.resources.configs').joinpath(resource_name)
            
            stable_temp_path = Path(_temp_dir.name).joinpath(resource_name.lstrip('/'))
            if traversable.is_dir():
                stable_temp_path.mkdir(parents=True, exist_ok=True)
                return stable_temp_path

            with resources.as_file(traversable) as p:
                if not stable_temp_path.exists():
                    stable_temp_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(p, stable_temp_path)
                return stable_temp_path
        except (FileNotFoundError, KeyError):
            raise VolumeNotFoundError(f"Internal resource not found: '{resource_name}'")
    
    @property
    def origin(self):
        return self.original_path_str


    @override
    @property
    def parent(self):
        if self.is_resource:
            parent_str = str(PurePosixPath(rm_resource(self.origin)).parent)
            return self.__class__(add_resource(parent_str))
        return super().parent
    
    @override
    def __truediv__(self, other):
        if self.is_resource:
            return self.__class__(add_resource(str(PurePosixPath(rm_resource(self.origin)).joinpath(other))))
        return super().__truediv__(other)   
    
    @override
    def __rtruediv__(self, other):
        """we should not support this operation for resource:"""
        if self.is_resource:
            return NotImplemented
        return super().__rtruediv__(other)

    @override
    def is_absolute(self) -> bool:
        if self.is_resource:
            return False
        return is_path_absolute(self.original_path_str)

    def __repr__(self):
        # Provide a more informative repr
        return f"DNSBPath('{self.original_path_str}')"

    # __reduce__ relies on a simple parts-based constructor.
    def __reduce__(self):
        return (self.__class__, self.original_path_str)

def rm_resource(path: str):
    if path.startswith(constants.RESOURCE_PREFIX):
        return path[len(constants.RESOURCE_PREFIX):]
    return path

def add_resource(path: str):
    if path.startswith(constants.RESOURCE_PREFIX):
        return path
    return constants.RESOURCE_PREFIX + path

def is_path_valid(path: str) -> bool:
    """
        Check if a path is valid.
    """
    is_windows = False
    is_posix = False
    try:
        PureWindowsPath(path)
        is_windows = True
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise
    try:
        PurePosixPath(path)
        is_posix = True
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise 
    return is_windows or is_posix

def is_path_absolute(path: str) -> bool:
    """
        Check if a path is absolute.
    """
    is_absolute = False
    try:
        is_absolute = PurePosixPath(path).is_absolute()
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise
    if is_absolute:
        return True
    try:
        return PureWindowsPath(path).is_absolute()
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise