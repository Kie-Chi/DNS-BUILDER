from abc import ABC, abstractmethod
from typing import Dict, List
from datetime import datetime
import logging
import os
import fsspec
from morefs.dict import DictFS
from morefs.memory import MemFS
from importlib import resources
import git
import hashlib
from ..utils.typing_compat import override
from .path import DNSBPath, Path
from ..exceptions import (
    ProtocolError,
    InvalidPathError,
    UnsupportedFeatureError,
    ReadOnlyError,
    DNSBPathExistsError,
    DNSBPathNotFoundError,
    DNSBNotAFileError,
    DNSBNotADirectoryError,
)

logger = logging.getLogger(__name__)


def wrap_io_error(func):
    """Decorator to wrap IO errors into DNS-Builder exceptions."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileExistsError as e:
            raise DNSBPathExistsError(e) from e
        except FileNotFoundError as e:
            raise DNSBPathNotFoundError(e) from e
        except IsADirectoryError as e:
            raise DNSBNotAFileError(e) from e
        except NotADirectoryError as e:
            raise DNSBNotADirectoryError(e) from e
        except Exception as e:
            raise e

    return wrapper

# --------------------------------------------------------
#
# Abstract Base FileSystem Interface
#
# --------------------------------------------------------
"""
    Abstract Base FileSystem Interface,
    define the basic methods for file system operations.
"""

# --------------------
#
# Abstract FileSystem
#
# --------------------

class FileSystem(ABC):
    """DNSB File System Abstract Base Class"""

    @abstractmethod
    def read_text(self, path: DNSBPath) -> str:
        """Read text from a file"""
        pass

    @abstractmethod
    def read_bytes(self, path: DNSBPath) -> bytes:
        """Read bytes from a file"""
        pass

    @abstractmethod
    def write_text(self, path: DNSBPath, content: str):
        """Write text to a file"""
        pass

    @abstractmethod
    def write_bytes(self, path: DNSBPath, content: bytes):
        """Write bytes to a file"""
        pass

    @abstractmethod
    def append_text(self, path: DNSBPath, content: str):
        """Append text to a file"""
        pass

    @abstractmethod
    def append_bytes(self, path: DNSBPath, content: bytes):
        """Append bytes to a file"""
        pass

    @abstractmethod
    def copy(self, src: DNSBPath, dst: DNSBPath):
        """Copy a path from src to dst"""
        pass

    @abstractmethod
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        """Copy a directory tree from src to dst"""
        pass

    @abstractmethod
    def exists(self, path: DNSBPath) -> bool:
        """Check if a path exists"""
        pass

    @abstractmethod
    def is_dir(self, path: DNSBPath) -> bool:
        """Check if a path is a directory"""
        pass

    @abstractmethod
    def is_file(self, path: DNSBPath) -> bool:
        """Check if a path is a file"""
        pass

    @abstractmethod
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        """Create a directory"""
        pass

    @abstractmethod
    def rmtree(self, path: DNSBPath):
        """Remove a directory recursively"""
        pass

    # NotImplemented methods
    # !!! Child-FileSystem Override these methods if needed
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        """List directory contents"""
        return NotImplemented

    def remove(self, path: DNSBPath):
        """Remove a file or directory"""
        return NotImplemented

    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        """Glob a path pattern"""
        return NotImplemented

    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        """Glob a path pattern recursively"""
        return NotImplemented
    
    def absolute(self, path: DNSBPath) -> DNSBPath:
        """Get the absolute path"""
        return NotImplemented

    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        return NotImplemented
    

# --------------------------------------------------------
#
# User FileSystem
#
# --------------------------------------------------------
"""
    User FileSystem,
    provide file system operations for user files.
"""

# --------------------
#
# Application FileSystem
#
# --------------------

class AppFileSystem(FileSystem):
    """
        support a lot kind of file system, 
        like file, resource, http, s3, etc.
    """
    _handlers: Dict[str, FileSystem] = {}

    def __init__(self):
        # register default file system handlers
        self.register_handler("file", DiskFileSystem())
        self.register_handler("temp", MemoryFileSystem())
        self.register_handler("resource", ResourceFileSystem())
        self.register_handler("git", GitFileSystem(self))

        
    def register_handler(self, protocol: str, handler: FileSystem):
        """Register a file system handler for a specific protocol."""
        self._handlers[protocol] = handler

    def unregister_handler(self, protocol: str):
        """Unregister the file system handler for a specific protocol."""
        if protocol in self._handlers:
            del self._handlers[protocol]

    @classmethod
    def _delegator(cls, method_name: str):
        def decorator(self, path: DNSBPath, *args, **kwargs):
            handler = self._get_handler(path)
            method = getattr(handler, method_name, None)
            if method is None:
                raise NotImplementedError(f"FileSystem handler for protocol '{path.protocol}' does not support '{method_name}'")
            return method(path, *args, **kwargs)
        return decorator

    def _get_handler(self, path: DNSBPath) -> 'FileSystem':
        """Get the file system handler for a specific path."""
        protocol = path.protocol
        handler = self._handlers.get(protocol)
        if not handler:
            raise ProtocolError(
                f"No filesystem handler registered for protocol: '{protocol}'"
            )
        return handler

    @override
    @wrap_io_error
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        return AppFileSystem._delegator("listdir")(self, path)

    # Not-Std Methods
    @override
    @wrap_io_error
    def remove(self, path: DNSBPath):
        return AppFileSystem._delegator("remove")(self, path)

    @override
    @wrap_io_error
    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return AppFileSystem._delegator("glob")(self, path, pattern)

    @override
    @wrap_io_error
    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return AppFileSystem._delegator("rglob")(self, path, pattern)

    @override
    @wrap_io_error
    def absolute(self, path: DNSBPath) -> DNSBPath:
        return AppFileSystem._delegator("absolute")(self, path)

    # Std Methods
    @override
    @wrap_io_error
    def read_text(self, path: DNSBPath) -> str:
        return AppFileSystem._delegator("read_text")(self, path)

    @override
    @wrap_io_error
    def write_text(self, path: DNSBPath, content: str):
        return AppFileSystem._delegator("write_text")(self, path, content)
    
    @override
    @wrap_io_error
    def append_text(self, path: DNSBPath, content: str):
        return AppFileSystem._delegator("append_text")(self, path, content)

    @override
    def exists(self, path: DNSBPath) -> bool:
        return AppFileSystem._delegator("exists")(self, path)

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        return AppFileSystem._delegator("is_dir")(self, path)

    @override
    def is_file(self, path: DNSBPath) -> bool:
        return AppFileSystem._delegator("is_file")(self, path)      

    @override
    @wrap_io_error
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        return AppFileSystem._delegator("mkdir")(self, path, parents=parents, exist_ok=exist_ok)

    @override
    @wrap_io_error
    def rmtree(self, path: DNSBPath):
        return AppFileSystem._delegator("rmtree")(self, path)

    @override
    @wrap_io_error
    def copy(self, src: DNSBPath, dst: DNSBPath):
        src_handler = self._get_handler(src)
        dst_handler = self._get_handler(dst)

        if src_handler is dst_handler:
            src_handler.copy(src, dst)
            return

        logger.debug(
            f"Performing cross-filesystem copy from '{src.protocol}' to '{dst.protocol}'"
        )
        content = src_handler.read_bytes(src)
        dst_handler.write_bytes(dst, content)

    @override
    @wrap_io_error
    def append_bytes(self, path: DNSBPath, content: bytes):
        return AppFileSystem._delegator("append_bytes")(self, path, content)
    
    @override
    @wrap_io_error
    def read_bytes(self, path: DNSBPath) -> bytes:
        return AppFileSystem._delegator("read_bytes")(self, path)

    @override
    @wrap_io_error
    def write_bytes(self, path: DNSBPath, content: bytes):
        return AppFileSystem._delegator("write_bytes")(self, path, content)

    @override
    @wrap_io_error
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        return self._get_handler(path).stat(path)

    @override
    @wrap_io_error
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        src_handler = self._get_handler(src)
        dst_handler = self._get_handler(dst)
        if src_handler is dst_handler and isinstance(src_handler, DiskFileSystem):
            src_handler.copytree(src, dst)
            return

        if isinstance(dst_handler, DiskFileSystem):
            if isinstance(src_handler, GitFileSystem):
                src_handler.copy2disk(src, dst)
                return
            if isinstance(src_handler, ResourceFileSystem):
                src_handler.copy2disk(src, dst, dst_handler)
                return

        raise UnsupportedFeatureError(
            f"Cross-filesystem copytree from '{src.protocol}' to '{dst.protocol}' is not yet implemented."
        )

# --------------------
#
# Generic FileSystem
#
# --------------------

class GenericFileSystem(FileSystem, ABC):
    """Generic File System base class for fsspec and morefs implementations"""

    def __init__(self, fs_instance, name=None):
        """
        Initialize with a filesystem instance
        
        Args:
            fs_instance: The underlying filesystem instance (fsspec or morefs)
            name: Optional name for logging purposes
        """
        self.fs = fs_instance
        self.name = name or f"{type(fs_instance).__name__}"

    @abstractmethod
    def path2str(self, path: DNSBPath) -> str:
        """Convert DNSBPath to string"""
        pass

    @override
    def read_text(self, path: DNSBPath, encoding: str = "utf-8") -> str:
        logger.debug(f"[{self.name}] Reading from: {path}")
        with self.fs.open(self.path2str(path), "r", encoding=encoding) as f:
            return f.read()

    @override
    def read_bytes(self, path: DNSBPath) -> bytes:
        logger.debug(f"[{self.name}] Reading bytes from: {path}")
        with self.fs.open(self.path2str(path), "rb") as f:
            return f.read()

    @override
    def write_text(self, path: DNSBPath, content: str, encoding: str = "utf-8"):
        logger.debug(f"[{self.name}] Writing to: {path}")
        self.fs.mkdirs(self.path2str(path.parent), exist_ok=True)
        with self.fs.open(self.path2str(path), "w", encoding=encoding) as f:
            f.write(content)

    @override
    def write_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Writing bytes to: {path}")
        self.fs.mkdirs(self.path2str(path.parent), exist_ok=True)
        with self.fs.open(self.path2str(path), "wb") as f:
            f.write(content)

    @override
    def append_text(self, path: DNSBPath, content: str, encoding: str = "utf-8"):
        logger.debug(f"[{self.name}] Appending to: {path}")
        self.fs.mkdirs(self.path2str(path.parent), exist_ok=True)
        with self.fs.open(self.path2str(path), "a", encoding=encoding) as f:
            f.write(content)

    @override
    def append_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Appending bytes to: {path}")
        self.fs.mkdirs(self.path2str(path.parent), exist_ok=True)
        with self.fs.open(self.path2str(path), "ab") as f:
            f.write(content)

    @override
    def copy(self, src: DNSBPath, dst: DNSBPath):
        logger.debug(f"[{self.name}] Copying path '{src}' to '{dst}'")
        self.fs.mkdirs(self.path2str(dst.parent), exist_ok=True)
        self.fs.copy(self.path2str(src), self.path2str(dst))

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        logger.debug(f"[{self.name}] Copying tree '{src}' to '{dst}'")
        self.fs.cp(self.path2str(src), self.path2str(dst), recursive=True)

    @override
    def exists(self, path: DNSBPath) -> bool:
        return self.fs.exists(self.path2str(path))

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        return self.fs.isdir(self.path2str(path))

    @override
    def is_file(self, path: DNSBPath) -> bool:
        return self.fs.isfile(self.path2str(path))

    @override
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        self.fs.mkdirs(self.path2str(path), exist_ok=exist_ok)

    @override
    def rmtree(self, path: DNSBPath):
        if self.fs.exists(self.path2str(path)):
            self.fs.rm(self.path2str(path), recursive=True)
        else:
            logger.debug(f"Path {path} does not exist, skipping rmtree.")

    @override
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        return [DNSBPath(p) for p in self.fs.ls(self.path2str(path))]

    @override
    def remove(self, path: DNSBPath):
        self.fs.rm(self.path2str(path))

    @override
    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return [DNSBPath(p) for p in self.fs.glob(self.path2str(path / pattern))]

    @override
    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return [DNSBPath(p) for p in self.fs.glob(self.path2str(path / f"**/{pattern}"))]

class FsspecFileSystem(GenericFileSystem):
    """fsspec-based File System"""

    def __init__(self, protocol="file"):
        fs_instance = fsspec.filesystem(protocol)
        super().__init__(fs_instance, name=f"{protocol}FS")
        self.protocol = protocol

    @override
    def path2str(self, path: DNSBPath) -> str:
        """Convert DNSBPath to string"""
        return str(path)

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        stat_info = self.fs.stat(self.path2str(path))

        # fsspec may return a dict, convert to os.stat_result
        if isinstance(stat_info, dict):
            # Extract common fields from fsspec stat dict
            size = stat_info.get("size", 0)
            mtime = stat_info.get("mtime", 0)
            mode = stat_info.get(
                "mode", 0o100644 if stat_info.get("type") == "file" else 0o040755
            )

            # Create os.stat_result from dict
            return os.stat_result(
                (
                    mode,  # st_mode
                    0,  # st_ino (inode number)
                    0,  # st_dev (device)
                    1,  # st_nlink (number of hard links)
                    0,  # st_uid (user id)
                    0,  # st_gid (group id)
                    size,  # st_size
                    mtime,  # st_atime (access time)
                    mtime,  # st_mtime (modification time)
                    mtime,  # st_ctime (creation time)
                )
            )
        else:
            # Already an os.stat_result
            return stat_info

class MorefsFileSystem(GenericFileSystem):
    """morefs-based File System"""

    def __init__(self, fs_type="dict"):
        """
        Initialize morefs filesystem

        Args:
            fs_type: Type of morefs filesystem ("dict" or "mem")
        """
        if fs_type == "dict":
            fs_instance = DictFS()
        elif fs_type == "mem":
            fs_instance = MemFS()
        else:
            raise ValueError(f"Unsupported morefs type: {fs_type}")
        super().__init__(fs_instance, name=f"Morefs{fs_type.title()}FS")
        self.fs_type = fs_type

    @override
    def path2str(self, path: DNSBPath) -> str:
        """Convert DNSBPath to string"""
        return path.__path__()

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        stat_info = self.fs.stat(self.path2str(path))

        if not isinstance(stat_info, dict):
            raise TypeError(
                f"[{self.name}] Expected a dict from stat, but got {type(stat_info)}"
            )

        epoch = datetime(1970, 1, 1)
        mtime = stat_info.get("modified", epoch).timestamp()
        atime = stat_info.get("accessed", epoch).timestamp()
        ctime = stat_info.get("created", epoch).timestamp()

        size = stat_info.get("size", 0)

        # Infer mode, as morefs doesn't provide it
        ftype = stat_info.get("type", "file")
        mode = 0o040755 if ftype == "directory" else 0o100644

        return os.stat_result(
            (
                mode,  # st_mode
                0,  # st_ino
                0,  # st_dev
                1,  # st_nlink
                0,  # st_uid
                0,  # st_gid
                size,  # st_size
                atime,  # st_atime
                mtime,  # st_mtime
                ctime,  # st_ctime
            )
        )

# --------------------
#
# Generic Disk FileSystem
#
# --------------------

class DiskFileSystem(FsspecFileSystem):
    """Local disk file system using fsspec"""

    def __init__(self):
        super().__init__(protocol="file")

    @override
    def absolute(self, path: DNSBPath) -> DNSBPath:
        return DNSBPath(Path(path).absolute())

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        return Path(str(path)).stat()

# --------------------
#
# Generic Network FileSystem
#
# --------------------

class NetworkFileSystem(FsspecFileSystem):
    """Network file system using fsspec"""

    def __init__(self, protocol):
        super().__init__(protocol=protocol)


# --------------------------------------------------------
#
# Self-defined FileSystem
#
# --------------------------------------------------------
"""
    following are Self-defined FileSystems we used in DNS-Builder,
    they support self-defined protocol to fetch resource or 
    support self-defined filesystem implement `FileSystem Interface`
"""


# --------------------
#
# `resource`-protocol FileSystem
#
# --------------------

class ResourceFileSystem(FileSystem):
    """Resource Protocol FileSystem, ReadOnly"""

    def _get_resource_traversable(self, path: DNSBPath) -> resources.abc.Traversable:
        """ get Traversable object for resource"""
        if path.protocol != "resource":
            raise ProtocolError(f"Only resource protocol path is supported, got {path.protocol}")

        package = resources.files("dnsbuilder.resources")
        traversable = package
        for part in path.parts[1:]:
            traversable = traversable.joinpath(part)
        return traversable

    @override
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        return [path / DNSBPath(p).name for p in self._get_resource_traversable(path).iterdir()]

    @override
    def read_text(self, path: DNSBPath, encoding: str = "utf-8") -> str:
        logger.debug(f"[ResourceFS] Reading from resource: {path}")
        return self._get_resource_traversable(path).read_text(encoding=encoding)

    @override
    def read_bytes(self, path: DNSBPath) -> bytes:
        logger.debug(f"[ResourceFS] Reading bytes from resource: {path}")
        return self._get_resource_traversable(path).read_bytes()

    @override
    def exists(self, path: DNSBPath) -> bool:
        try:
            t = self._get_resource_traversable(path)
            return t.is_file() or t.is_dir()
        except (ModuleNotFoundError, FileNotFoundError):
            return False

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        try:
            return self._get_resource_traversable(path).is_dir()
        except (ModuleNotFoundError, FileNotFoundError):
            return False

    @override
    def is_file(self, path: DNSBPath) -> bool:
        try:
            return self._get_resource_traversable(path).is_file()
        except (ModuleNotFoundError, FileNotFoundError):
            return False

    def _raise_read_only(self, path: DNSBPath):
        raise ReadOnlyError(f"Can not write to resource: {path}")

    @override
    def write_text(self, path: DNSBPath, content: str, encoding: str = "utf-8"):
        self._raise_read_only(path)

    @override
    def write_bytes(self, path: DNSBPath, content: bytes):
        self._raise_read_only(path)

    @override
    def append_text(self, path: DNSBPath, content: str, encoding: str = "utf-8"):
        self._raise_read_only(path)

    @override
    def append_bytes(self, path: DNSBPath, content: bytes):
        self._raise_read_only(path)

    @override
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        self._raise_read_only(path)

    @override
    def rmtree(self, path: DNSBPath):
        self._raise_read_only(path)

    @override
    def copy(self, src: DNSBPath, dst: DNSBPath):
        self._raise_read_only(dst)  # Can't copy *to* a resource

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        self._raise_read_only(dst)

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Return immutable stat information for resource files."""
        if not self.exists(path):
            raise DNSBPathNotFoundError(f"Resource path does not exist: {path}")
        
        # For resource files, we create a const
        if self.is_file(path):
            content = self.read_bytes(path)
            size = len(content)
            mtime = 0  # January 1, 1970
            mode = 0o100644  # Regular file with read permissions
        else:
            # Directory
            size = 0
            mtime = 0
            mode = 0o040755  # Directory with read/execute permissions
        
        return os.stat_result((
            mode,           # st_mode
            0,              # st_ino (inode number)
            0,              # st_dev (device)
            1,              # st_nlink (number of hard links)
            0,              # st_uid (user id)
            0,              # st_gid (group id)
            size,           # st_size
            mtime,          # st_atime (access time)
            mtime,          # st_mtime (modification time)
            mtime           # st_ctime (creation time)
        ))

    def copy2disk(self, src: DNSBPath, dst: DNSBPath, disk_fs: FileSystem):
        src_trav = self._get_resource_traversable(src)
        self._copy_to_disk_recursive(src_trav, dst, disk_fs)

    def _copy_to_disk_recursive(
        self,
        src_trav: resources.abc.Traversable,
        dst_path: DNSBPath,
        disk_fs: FileSystem,
    ):
        if src_trav.is_file():
            content = src_trav.read_bytes()
            disk_fs.write_bytes(dst_path, content)
        elif src_trav.is_dir():
            if not disk_fs.exists(dst_path):
                disk_fs.mkdir(dst_path, parents=True, exist_ok=True)

            for item in src_trav.iterdir():
                item_dst_path = dst_path / item.name
                self._copy_to_disk_recursive(item, item_dst_path, disk_fs)



# --------------------
#
# Memory (Fake) FileSystem
#
# --------------------

class MemoryFileSystem(FsspecFileSystem):
    """
    in-memory filesystem using fsspec
    """
    def __init__(self):
        super().__init__(protocol="memory")

class HyperMemoryFileSystem(MorefsFileSystem):
    """
    High-performance in-memory filesystem
    """
    def __init__(self, fs_type="mem"):
        super().__init__(fs_type=fs_type)


# --------------------
#
# Git FileSystem
#
# --------------------

class GitFileSystem(FileSystem):
    """
    A read-only filesystem for accessing files from Git repositories.
    Handles 'git://' URIs, clones repositories into a local cache,
    and allows reading files from specific branches, tags, or commits.
    """

    def __init__(self, cache_fs: FileSystem, cache_root: str = ".dnsb_cache"):
        self.cache_fs = cache_fs
        self.cache_root = DNSBPath(cache_root)
        self.name = "GitFS"
        self._synced_repos = set()
        self._init_cache()

    def _init_cache(self):
        """Ensures the cache root directory exists."""
        if not self.cache_fs.exists(self.cache_root):
            logger.debug(
                f"[{self.name}] Creating cache directory at '{self.cache_root}'"
            )
            self.cache_fs.mkdir(self.cache_root, parents=True, exist_ok=True)

    def _parse_path(self, path: DNSBPath) -> tuple[str, str, str, DNSBPath]:
        """Parses a git URI into its components."""
        if path.protocol != "git":
            raise UnsupportedFeatureError(f"Unsupported protocol: {path.protocol}")

        repo_url = f"https://{path.host}{path.__path__()}"

        ref = "HEAD"
        query = path.query
        if "ref" in query and query["ref"]:
            ref = query["ref"][0]

        path_in_repo = path.fragment
        if not path_in_repo:
            raise InvalidPathError(
                "Path in repository must be specified in the URI fragment (e.g., #path/to/file)"
            )

        repo_hash = hashlib.sha256(repo_url.encode()).hexdigest()
        local_repo_path = self.cache_root / repo_hash

        return repo_url, ref, path_in_repo, local_repo_path

    def _get_synced_repo_path(self, path: DNSBPath) -> DNSBPath:
        """
        Ensures the repository is cloned/updated and at the correct ref.
        Returns the absolute path to the requested file within the cache.
        """
        repo_url, ref, path_in_repo, local_repo_path = self._parse_path(path)

        # Create a unique key for this repo and ref for this run
        cache_key = f"{repo_url}@{ref}"
        
        if cache_key in self._synced_repos:
            logger.debug(f"[{self.name}] '{cache_key}' already synced in this run. Using local cache.")
        else:
            logger.debug(f"[{self.name}] Syncing repository for '{cache_key}'...")
            local_repo_str = str(local_repo_path)
    
            if not self.cache_fs.exists(local_repo_path):
                logger.debug(f"[{self.name}] Cloning '{repo_url}' to '{local_repo_path}'...")
                git.Repo.clone_from(repo_url, local_repo_str)
                repo = git.Repo(local_repo_str)
            else:
                logger.debug(
                    f"[{self.name}] Repository '{repo_url}' found in cache. Fetching updates..."
                )
                repo = git.Repo(local_repo_str)
                try:
                    repo.remotes.origin.fetch()
                except git.exc.GitCommandError as e:
                    logger.warning(
                        f"[{self.name}] Failed to fetch updates for '{repo_url}': {e}. Using cached version."
                    )
    
            logger.debug(f"[{self.name}] Checking out ref '{ref}' for '{repo_url}'...")
            try:
                repo.git.checkout(ref)
                # If the ref is a branch (not a tag or commit hash), pull the latest changes.
                if ref in repo.heads:
                    logger.debug(f"[{self.name}] Pulling latest changes for branch '{ref}'...")
                    repo.remotes.origin.pull()
    
            except git.exc.GitCommandError as e:
                raise DNSBPathNotFoundError(
                    f"Ref '{ref}' not found in repository '{repo_url}': {e}"
                ) from e
            
            # Mark this repo+ref as synced for this run
            self._synced_repos.add(cache_key)
            logger.debug(f"[{self.name}] Sync complete for '{cache_key}'.")


        final_path = local_repo_path / path_in_repo
        if not self.cache_fs.exists(final_path):
            raise DNSBPathNotFoundError(f"Path '{path_in_repo}' not found in repository '{repo_url}' at ref '{ref}'.")
            
        return final_path

    @override
    def exists(self, path: DNSBPath) -> bool:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.exists(full_path)
        except (DNSBPathNotFoundError, InvalidPathError, ValueError):
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Error checking existence for '{path}': {e}")
            return False

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.is_dir(full_path)
        except (DNSBPathNotFoundError, InvalidPathError, ValueError):
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Error in is_dir for '{path}': {e}")
            return False

    @override
    def is_file(self, path: DNSBPath) -> bool:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.is_file(full_path)
        except (DNSBPathNotFoundError, InvalidPathError, ValueError):
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Error in is_file for '{path}': {e}")
            return False

    @override
    def read_text(self, path: DNSBPath) -> str:
        full_path = self._get_synced_repo_path(path)
        logger.debug(f"[{self.name}] Reading text from cached git path: {full_path}")
        return self.cache_fs.read_text(full_path)

    @override
    def read_bytes(self, path: DNSBPath) -> bytes:
        full_path = self._get_synced_repo_path(path)
        logger.debug(f"[{self.name}] Reading bytes from cached git path: {full_path}")
        return self.cache_fs.read_bytes(full_path)

    def _raise_read_only(self, path: DNSBPath):
        raise ReadOnlyError(f"Git filesystem is read-only. Cannot write to '{path}'.")

    @override
    def write_text(self, path: DNSBPath, content: str):
        self._raise_read_only(path)

    @override
    def write_bytes(self, path: DNSBPath, content: bytes):
        self._raise_read_only(path)

    @override
    def append_text(self, path: DNSBPath, content: str):
        self._raise_read_only(path)

    @override
    def append_bytes(self, path: DNSBPath, content: bytes):
        self._raise_read_only(path)

    @override
    def copy(self, src: DNSBPath, dst: DNSBPath):
        self._raise_read_only(dst)

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        self._raise_read_only(dst)

    @override
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        self._raise_read_only(path)

    @override
    def rmtree(self, path: DNSBPath):
        self._raise_read_only(path)

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.stat(full_path)
        except Exception as e:
            logger.error(f"[{self.name}] Error in stat for '{path}': {e}")
            raise

    def copy2disk(self, src: DNSBPath, dst: DNSBPath):
        try:
            full_path = self._get_synced_repo_path(src)
            if self.cache_fs.is_dir(full_path):
                self.cache_fs.copytree(full_path, dst)
            elif self.cache_fs.is_file(full_path):
                self.cache_fs.copy(full_path, dst)
        except Exception as e:
            logger.error(f"[{self.name}] Error in copy2disk for '{src}' to '{dst}': {e}")
            raise


# --------------------
#
# Helper Functions
#
# --------------------

def create_app_fs(use_vfs: bool = False) -> "FileSystem" :
    """
    Create the appropriate FileSystem for the application.
    """
    app_fs = AppFileSystem()
    if not use_vfs:
        app_fs.register_handler("file", DiskFileSystem())
    else:
        app_fs.register_handler("file", MemoryFileSystem())
    return app_fs