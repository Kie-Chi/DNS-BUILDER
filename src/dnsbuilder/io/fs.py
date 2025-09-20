from abc import ABC, abstractmethod
from typing import override, Union, Dict
import logging
import fsspec
from importlib import resources
from .path import DNSBPath

logger = logging.getLogger(__name__)

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
    def __init__(self):
        self._handlers: Dict[str, FileSystem] = {}
        # register default file system handlers
        self.register_handler("file", DiskFileSystem())

        
    def register_handler(self, protocol: str, handler: FileSystem):
        """Register a file system handler for a specific protocol."""
        self._handlers[protocol] = handler

    def unregister_handler(self, protocol: str):
        """Unregister the file system handler for a specific protocol."""
        if protocol in self._handlers:
            del self._handlers[protocol]

    def _get_handler(self, location: DNSBPath) -> FileSystem:
        """Get the file system handler for a specific location."""
        handler = self._handlers.get(location.protocol)
        if not handler:
            raise ValueError(
                f"No filesystem handler registered for protocol: '{location.protocol}'"
            )
        return handler

    @override
    def read_text(self, location: DNSBPath) -> str:
        return self._get_handler(location).read_text(location)

    @override
    def write_text(self, location: DNSBPath, content: str):
        return self._get_handler(location).write_text(location, content)
    
    @override
    def append_text(self, location: DNSBPath, content: str):
        return self._get_handler(location).append_text(location, content)

    @override
    def exists(self, location: DNSBPath) -> bool:
        return self._get_handler(location).exists(location)

    @override
    def is_dir(self, location: DNSBPath) -> bool:
        return self._get_handler(location).is_dir(location)

    @override
    def is_file(self, location: DNSBPath) -> bool:
        return self._get_handler(location).is_file(location)

    @override
    def mkdir(self, location: DNSBPath, parents: bool = False, exist_ok: bool = False):
        return self._get_handler(location).mkdir(location, parents=parents, exist_ok=exist_ok)

    @override
    def rmtree(self, location: DNSBPath):
        return self._get_handler(location).rmtree(location)

    @override
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
    def append_bytes(self, location: DNSBPath, content: bytes):
        return self._get_handler(location).append_bytes(location, content)

    @override
    def read_bytes(self, location: DNSBPath) -> bytes:
        return self._get_handler(location).read_bytes(location)

    @override
    def write_bytes(self, location: DNSBPath, content: bytes):
        return self._get_handler(location).write_bytes(location, content)

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        src_handler = self._get_handler(src)
        dst_handler = self._get_handler(dst)
        if src_handler is dst_handler and isinstance(src_handler, DiskFileSystem):
            src_handler.copytree(src, dst)
        else:
            raise NotImplementedError(
                "Cross-filesystem copytree is not yet implemented."
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
            raise TypeError(f"Only resource protocol path is supported, got {path.protocol}")

        package = resources.files("dnsbuilder.resources")
        traversable = package
        for part in path.parts[1:]:
            traversable = traversable.joinpath(part)
        return traversable

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
        raise IOError(f"Can not write to resource: {path}")

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