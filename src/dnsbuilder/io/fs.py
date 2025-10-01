from abc import ABC, abstractmethod
from typing import Union, Dict, List
import logging
import fsspec
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

class GenericFileSystem(FileSystem):
    """fsspec Generic File System"""

    def __init__(self, protocol="file"):
        self.fs = fsspec.filesystem(protocol)
        self.protocol = protocol
        self.name = f"{protocol}FS"

    @override
    def read_text(self, path: DNSBPath, encoding: str = "utf-8") -> str:
        logger.debug(f"[{self.name}] Reading from disk: {path}")
        with self.fs.open(str(path), "r", encoding=encoding) as f:
            return f.read()

    @override
    def read_bytes(self, path: DNSBPath) -> bytes:
        logger.debug(f"[{self.name}] Reading bytes from disk: {path}")
        with self.fs.open(str(path), "rb") as f:
            return f.read()

    @override
    def write_text(self, path: DNSBPath, content: str, encoding: str = "utf-8"):
        logger.debug(f"[{self.name}] Writing to disk: {path}")
        self.fs.mkdirs(str(path.parent), exist_ok=True)
        with self.fs.open(str(path), "w", encoding=encoding) as f:
            f.write(content)

    @override
    def write_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Writing bytes to disk: {path}")
        self.fs.mkdirs(str(path.parent), exist_ok=True)
        with self.fs.open(str(path), "wb") as f:
            f.write(content)

    @override
    def append_text(self, path: DNSBPath, content: str, encoding: str = "utf-8"):
        logger.debug(f"[{self.name}] Appending to disk: {path}")
        self.fs.mkdirs(str(path.parent), exist_ok=True)
        with self.fs.open(str(path), "a", encoding=encoding) as f:
            f.write(content)

    @override
    def append_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Appending bytes to disk: {path}")
        self.fs.mkdirs(str(path.parent), exist_ok=True)
        with self.fs.open(str(path), "ab") as f:
            f.write(content)

    @override
    def copy(self, src: DNSBPath, dst: DNSBPath):
        logger.debug(f"[{self.name}] Copying disk path '{src}' to '{dst}'")
        self.fs.mkdirs(str(dst.parent), exist_ok=True)
        self.fs.copy(str(src), str(dst))

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        logger.debug(f"[{self.name}] Copying disk tree '{src}' to '{dst}'")
        self.fs.put(str(src), str(dst), recursive=True)

    @override
    def exists(self, path: DNSBPath) -> bool:
        return self.fs.exists(str(path))

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        return self.fs.isdir(str(path))

    @override
    def is_file(self, path: DNSBPath) -> bool:
        return self.fs.isfile(str(path))

    @override
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        self.fs.mkdirs(str(path), exist_ok=exist_ok)

    @override
    def rmtree(self, path: DNSBPath):
        if self.fs.exists(str(path)):
            self.fs.rm(str(path), recursive=True)
        else:
            logger.debug(f"Path {path} does not exist, skipping rmtree.")

    @override
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        return [DNSBPath(p) for p in self.fs.ls(str(path))]

    @override
    def remove(self, path: DNSBPath):
        self.fs.rm(str(path))

    @override
    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return [DNSBPath(p) for p in self.fs.glob(str(path / pattern))]

    @override
    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return [DNSBPath(p) for p in self.fs.glob(str(path / pattern))]

# --------------------
#
# Generic Disk FileSystem
#
# --------------------

class DiskFileSystem(GenericFileSystem):
    """Disk File System"""

    def __init__(self):
        super().__init__(protocol="file")
        self.name = "DiskFS"

    @override
    def absolute(self, path: DNSBPath) -> DNSBPath:
        return DNSBPath(Path(path).absolute())

# --------------------
#
# Generic Network FileSystem
#
# --------------------

class NetworkFileSystem(GenericFileSystem):
    """Network File System"""

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

class MemoryFileSystem(FileSystem):
    """
    An in-memory implementation of the FileSystem ABC for fast, isolated testing.
    It simulates a POSIX-like file system.
    """

    def __init__(self):
        # The root directory always exists.
        self.files: Dict[str, Union[bytes, None]] = {"/": None}
        self.name = "MemoryFS"

    def _get_path_str(self, path: DNSBPath) -> str:
        """Normalizes a path object to a consistent string representation for use as a dictionary key."""
        return path.__path__()

    @override
    def exists(self, path: DNSBPath) -> bool:
        return self._get_path_str(path) in self.files

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        path_str = self._get_path_str(path)
        return self.exists(path) and self.files[path_str] is None
    
    @override
    def is_file(self, path: DNSBPath) -> bool:
        path_str = self._get_path_str(path)
        return self.exists(path) and self.files[path_str] is not None

    @override
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        path_str = self._get_path_str(path)

        if self.exists(path):
            if self.is_file(path):
                raise FileExistsError(f"Path exists and is a file: '{path_str}'")
            if not exist_ok:
                raise FileExistsError(f"Path exists and is a directory: '{path_str}'")
            return  # Directory exists and exist_ok is True

        parent_path = path.parent
        if not self.exists(parent_path):
            if not parents:
                raise FileNotFoundError(
                    f"Parent directory does not exist: '{self._get_path_str(parent_path)}'"
                )
            self.mkdir(parent_path, parents=True, exist_ok=True)

        self.files[path_str] = None  # Mark as a directory

    @override
    def write_text(self, path: DNSBPath, content: str):
        logger.debug(f"[{self.name}] Writing to memory: {path}")
        path_str = self._get_path_str(path)
        if self.is_dir(path):
            raise IsADirectoryError(f"Cannot write to a directory: '{path_str}'")

        # Ensure parent directory exists
        self.mkdir(path.parent, parents=True, exist_ok=True)
        self.files[path_str] = content.encode("utf-8")
    
    @override
    def write_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Writing bytes to memory: {path}")
        path_str = self._get_path_str(path)
        if self.is_dir(path):
            raise IsADirectoryError(f"Cannot write to a directory: '{path_str}'")

        # Ensure parent directory exists
        self.mkdir(path.parent, parents=True, exist_ok=True)
        self.files[path_str] = content

    @override
    def read_text(self, path: DNSBPath) -> str:
        logger.debug(f"[{self.name}] Reading from memory: {path}")
        path_str = self._get_path_str(path)
        if not self.exists(path):
            raise FileNotFoundError(f"No such file or directory: '{path_str}'")
        if self.is_dir(path):
            raise IsADirectoryError(f"Cannot read from a directory: '{path_str}'")

        return self.files[path_str].decode("utf-8")

    @override
    def read_bytes(self, path: DNSBPath) -> bytes:
        logger.debug(f"[{self.name}] Reading bytes from memory: {path}")
        path_str = self._get_path_str(path)
        if not self.exists(path):
            raise FileNotFoundError(f"No such file or directory: '{path_str}'")
        if self.is_dir(path):
            raise IsADirectoryError(f"Cannot read from a directory: '{path_str}'")

        return self.files[path_str]

    @override
    def append_text(self, path: DNSBPath, content: str):
        logger.debug(f"[{self.name}] Appending to memory: {path}")
        path_str = self._get_path_str(path)
        if not self.exists(path):
            self.write_text(path, content)
            return
        if self.is_dir(path):
            raise IsADirectoryError(f"Cannot append to a directory: '{path_str}'")
        current_content = self.read_bytes(path)
        self.write_bytes(path, current_content + content.encode("utf-8"))

    @override
    def append_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Appending bytes to memory: {path}")
        path_str = self._get_path_str(path)
        if not self.exists(path):
            self.write_bytes(path, content)
            return
        if self.is_dir(path):
            raise IsADirectoryError(f"Cannot append to a directory: '{path_str}'")
        current_content = self.read_bytes(path)
        self.write_bytes(path, current_content + content)

    @override
    def rmtree(self, path: DNSBPath):
        """Recursively removes a directory or a single file."""
        path_str = self._get_path_str(path)
        if not self.exists(path):
            return  # Silently ignore non-existent paths, like shutil.rmtree

        if self.is_file(path):
            del self.files[path_str]
            return

        # It's a directory, remove it and everything inside it
        prefix = path_str if path_str.endswith("/") else f"{path_str}/"
        keys_to_delete = [k for k in self.files if k.startswith(prefix)]
        keys_to_delete.append(path_str)  # Also remove the directory itself

        for k in set(keys_to_delete):
            if k in self.files:
                del self.files[k]

    @override
    def copy(self, src: DNSBPath, dst: DNSBPath):
        """
        Copies a single file from src to dst. Mimics `shutil.copy`.
            - If src is a directory, raises IsADirectoryError.
            - If dst is a directory, src is copied into it.
            - If dst is a file, it is overwritten.
        """
        logger.debug(f"[{self.name}] Copying memory path '{src}' to '{dst}'")
        src_str = self._get_path_str(src)
        if not self.exists(src):
            raise FileNotFoundError(f"Source path does not exist: '{src_str}'")
        if self.is_dir(src):
            raise IsADirectoryError(
                f"Source path is a directory, use copy_tree instead: '{src_str}'"
            )

        content = self.read_bytes(src)
        final_dst = dst

        if self.is_dir(dst):
            # Destination is a directory, copy the file inside it.
            final_dst = dst / src.name

        self.write_bytes(final_dst, content)

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        """Recursively copies a directory tree. Mimics `shutil.copytree`."""
        logger.debug(f"[{self.name}] Copying memory tree '{src}' to '{dst}'")
        src_str = self._get_path_str(src)
        if not self.is_dir(src):
            raise NotADirectoryError(f"Source path is not a directory: '{src_str}'")

        # Create destination directory
        self.mkdir(dst, parents=True, exist_ok=True)

        src_prefix = src_str if src_str.endswith("/") else f"{src_str}/"

        # Iterate over all items in the filesystem
        for path_str, content in list(self.files.items()):
            if path_str.startswith(src_prefix):
                # Get the relative path from the source directory
                relative_path = path_str[len(src_prefix) :]

                # Construct the full destination path
                new_dst_path = dst / relative_path

                if content is None:  # It's a directory
                    self.mkdir(new_dst_path, parents=True, exist_ok=True)
                else:  # It's a file
                    self.write_bytes(new_dst_path, content)

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
    if use_vfs:
        app_fs.register_handler("file", DiskFileSystem())
    else:
        app_fs.register_handler("file", MemoryFileSystem())
    return app_fs