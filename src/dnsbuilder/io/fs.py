from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, IO, NamedTuple
from datetime import datetime, timezone
import logging
import os
import fsspec
from morefs.dict import DictFS
from morefs.memory import MemFS
from importlib import resources
import git
import hashlib
import threading
from ..utils import override
from .path import DNSBPath, Path
from .decorators import wrap_io_error, read_only
from contextlib import contextmanager
from ..exceptions import (
    ProtocolError,
    InvalidPathError,
    UnsupportedFeatureError,
    ReadOnlyError,
    DNSBPathNotFoundError,
)

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

    def __init__(self):
        """
        Initialize filesystem.
        """

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

    # Helper methods for path conversion
    def str2path(self, path_str: str, base_path: DNSBPath) -> DNSBPath:
        """
        Convert a string path from underlying filesystem back to DNSBPath,
        preserving the protocol from base_path.
        
        Args:
            path_str: Path string returned by underlying filesystem
            base_path: Original DNSBPath that contains protocol information
            
        Returns:
            DNSBPath with protocol preserved from base_path
        """
        # If the returned path already looks like it has a protocol, use it as-is
        if ":" in path_str and "/" in path_str:
            idx = path_str.index(":")
            if idx < path_str.index("/"):
                return DNSBPath(path_str)
        
        # Otherwise, reconstruct with the base path's protocol
        protocol = base_path.protocol
        if protocol and protocol != "file":
            # Strip leading slash if present
            clean_path = path_str.lstrip("/")
            return DNSBPath(f"{protocol}:/{clean_path}")
        
        return DNSBPath(path_str)

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
    
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        """Get the relative path to another path"""
        return NotImplemented

    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        return NotImplemented

    def open(self, path: DNSBPath, mode: str = "rb", **kwargs) -> IO:
        """Open a file"""
        return NotImplemented

    # Magic Method for some FileSystem
    @contextmanager
    def fallback(self, enable: bool): # ==> SandboxFileSystem/DiskFileSystem
        """Context manager to enable/disable fallback behavior"""
        try:
            yield
        finally:
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
    Multi-protocol file system dispatcher.
    
    This class explicitly delegates all FileSystem methods to protocol-specific handlers.
    It resolves paths against a `chroot` directory before dispatching.
    """

    def __init__(self, chroot: DNSBPath = None):
        super().__init__()
        self.chroot = self._norm(chroot)
        logger.debug(f"[AppFS] Initializing with chroot: {self.chroot}")
        self._handlers: Dict[str, FileSystem] = {}
        self.register_handler("file", DiskFileSystem())
        self.register_handler("raw", DiskFileSystem())
        self.register_handler("temp", HyperMemoryFileSystem())
        self.register_handler("resource", ResourceFileSystem())
        self.register_handler("git", GitFileSystem(DiskFileSystem()))
        self.register_handler("key", HyperMemoryFileSystem())   

    def register_handler(self, protocol: str, handler: FileSystem):
        """Register a file system handler for a specific protocol."""
        self._handlers[protocol] = handler

    def unregister_handler(self, protocol: str):
        """Unregister the file system handler for a specific protocol."""
        if protocol in self._handlers:
            del self._handlers[protocol]

    @staticmethod
    def _norm(chroot: DNSBPath) -> DNSBPath:
        """
        Normalize chroot to ensure consistency.
        """
        if not chroot:
            result = DNSBPath(Path.cwd())
            logger.debug(f"[AppFS] No chroot provided, using cwd: {result}")
            return result
        if chroot.is_absolute():
            logger.debug(f"[AppFS] Chroot is already absolute: {chroot}")
            return chroot
        if chroot.is_disk():
            result = DNSBPath(Path(chroot.__path__()).absolute())
            logger.debug(f"[AppFS] Normalized relative disk chroot to absolute: {result}")
            return result        
        logger.debug(f"[AppFS] Non-disk chroot passed through: {chroot}")
        return chroot

    def _resolve_path(self, path: DNSBPath) -> DNSBPath:
        """
        Resolve relative paths against chroot.
        Handles cross-protocol resolution (e.g., file:// path + git:// chroot).
        
        Args:
            path: Path to resolve
            
        Returns:
            Resolved absolute path with correct protocol
        """
        # If no chroot or path is already absolute, return as-is
        if not self.chroot or path.is_absolute():
            return path
        if self.chroot.protocol == "git":
            return self.chroot / path
        elif self.chroot.protocol == "resource":
            return self.chroot / path
        elif self.chroot.is_disk():
            if path.is_disk():
                resolved = self.chroot / path
                return DNSBPath(Path(resolved.__path__()).absolute())
            else:
                return path
        else:
            return self.chroot / path

    def _get_handler(self, path: DNSBPath) -> 'FileSystem':
        """Get the file system handler for a specific path."""
        protocol = path.protocol
        handler = self._handlers.get(protocol)
        if not handler:
            raise ProtocolError(
                f"No filesystem handler registered for protocol: '{protocol}'"
            )
        return handler
    
    def _delegate(self, method_name: str, path: DNSBPath, *args, **kwargs):
        """
        Delegate a FileSystem method based on path protocol.
        """
        resolved_path = self._resolve_path(path)
        handler = self._get_handler(resolved_path)
        method = getattr(handler, method_name, None)
        if method is None:
            raise NotImplementedError(
                f"FileSystem handler for protocol '{resolved_path.protocol}' "
                f"does not support '{method_name}'"
            )
        return method(resolved_path, *args, **kwargs)

    @override
    @wrap_io_error
    def read_text(self, path: DNSBPath) -> str:
        return self._delegate("read_text", path)

    @override
    @wrap_io_error
    def read_bytes(self, path: DNSBPath) -> bytes:
        return self._delegate("read_bytes", path)

    @override
    @wrap_io_error
    def write_text(self, path: DNSBPath, content: str):
        return self._delegate("write_text", path, content)

    @override
    @wrap_io_error
    def write_bytes(self, path: DNSBPath, content: bytes):
        return self._delegate("write_bytes", path, content)

    @override
    @wrap_io_error
    def append_text(self, path: DNSBPath, content: str):
        return self._delegate("append_text", path, content)

    @override
    @wrap_io_error
    def append_bytes(self, path: DNSBPath, content: bytes):
        return self._delegate("append_bytes", path, content)

    @override
    @wrap_io_error
    def exists(self, path: DNSBPath) -> bool:
        return self._delegate("exists", path)

    @override
    @wrap_io_error
    def is_dir(self, path: DNSBPath) -> bool:
        return self._delegate("is_dir", path)

    @override
    @wrap_io_error
    def is_file(self, path: DNSBPath) -> bool:
        return self._delegate("is_file", path)

    @override
    @wrap_io_error
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        return self._delegate("mkdir", path, parents=parents, exist_ok=exist_ok)

    @override
    @wrap_io_error
    def rmtree(self, path: DNSBPath):
        return self._delegate("rmtree", path)

    @override
    @wrap_io_error
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        return self._delegate("listdir", path)

    @override
    @wrap_io_error
    def remove(self, path: DNSBPath):
        return self._delegate("remove", path)

    @override
    @wrap_io_error
    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return self._delegate("glob", path, pattern)

    @override
    @wrap_io_error
    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return self._delegate("rglob", path, pattern)

    @override
    @wrap_io_error
    def absolute(self, path: DNSBPath) -> DNSBPath:
        return self._delegate("absolute", path)

    @override
    @wrap_io_error
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        return self._delegate("relative_to", path, other)

    @override
    @wrap_io_error
    def stat(self, path: DNSBPath) -> os.stat_result:
        return self._delegate("stat", path)

    @override
    @wrap_io_error
    def open(self, path: DNSBPath, mode: str = "rb", **kwargs) -> IO:
        return self._delegate("open", path, mode, **kwargs)

    @override
    def fallback(self, enable: bool):
        handler = self._handlers.get("file")
        if handler is None:
            raise ProtocolError("No handler registered for 'file' protocol.")
        return handler.fallback(enable)


    @override
    @wrap_io_error
    def copy(self, src: DNSBPath, dst: DNSBPath):
        # Resolve both paths against chroot
        resolved_src = self._resolve_path(src)
        resolved_dst = self._resolve_path(dst)
        
        src_handler = self._get_handler(resolved_src)
        dst_handler = self._get_handler(resolved_dst)

        if src_handler is dst_handler:
            src_handler.copy(resolved_src, resolved_dst)
            return

        logger.debug(
            f"Performing cross-filesystem copy from '{resolved_src.protocol}' to '{resolved_dst.protocol}'"
        )
        content = src_handler.read_bytes(resolved_src)
        dst_handler.write_bytes(resolved_dst, content)
    
    @override
    @wrap_io_error
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        logger.debug(f"[AppFS] copytree: {src} -> {dst}")
        
        # Resolve both paths against chroot
        resolved_src = self._resolve_path(src)
        resolved_dst = self._resolve_path(dst)
        
        src_handler = self._get_handler(resolved_src)
        dst_handler = self._get_handler(resolved_dst)
        logger.debug(f"[AppFS] src_handler={src_handler.__class__.__name__}, dst_handler={dst_handler.__class__.__name__}")
        
        if src_handler is dst_handler:
            if isinstance(src_handler, (DiskFileSystem, HyperMemoryFileSystem, MemoryFileSystem, SandboxFileSystem)):
                logger.debug(f"[AppFS] Using same-handler copytree ({src_handler.__class__.__name__})")
                src_handler.copytree(resolved_src, resolved_dst)
                return

        if isinstance(src_handler, GitFileSystem):
            logger.debug(f"[AppFS] Using GitFileSystem.copy2fs")
            src_handler.copy2fs(resolved_src, resolved_dst, dst_handler)
            return
        if isinstance(src_handler, ResourceFileSystem):
            logger.debug(f"[AppFS] Using ResourceFileSystem.copy2fs")
            src_handler.copy2fs(resolved_src, resolved_dst, dst_handler)
            return

        # Generic cross-filesystem copytree for supported filesystems
        if isinstance(src_handler, (HyperMemoryFileSystem, MemoryFileSystem, DiskFileSystem, SandboxFileSystem)) and \
           isinstance(dst_handler, (HyperMemoryFileSystem, MemoryFileSystem, DiskFileSystem, SandboxFileSystem)):
            logger.debug(f"[AppFS] Using generic cross-filesystem copytree")
            self._generic_copytree(resolved_src, resolved_dst, src_handler, dst_handler)
            return

        raise UnsupportedFeatureError(
            f"Cross-filesystem copytree from '{src_handler.__class__.__name__}' to '{dst_handler.__class__.__name__}' is not yet implemented."
        )
    
    def _generic_copytree(self, src: DNSBPath, dst: DNSBPath, src_handler: FileSystem, dst_handler: FileSystem):
        """Generic recursive copytree across filesystems"""
        if src_handler.is_file(src):
            content = src_handler.read_bytes(src)
            dst_handler.write_bytes(dst, content)
        elif src_handler.is_dir(src):
            if not dst_handler.exists(dst):
                dst_handler.mkdir(dst, parents=True, exist_ok=True)
            
            for item in src_handler.listdir(src):
                item_name = item.__rname__ if hasattr(item, '__rname__') else item.name
                src_item = src / item_name
                dst_item = dst / item_name
                self._generic_copytree(src_item, dst_item, src_handler, dst_handler)


from contextlib import contextmanager
import threading
class SandboxFileSystem(FileSystem):
    """
    A filesystem that composites a primary (e.g., memory) and a secondary 
    (e.g., disk) filesystem, providing a sandboxed environment with optional
    fallback to the secondary layer.
    - **Write Operations**: All modifications (write, mkdir, remove, etc.) are
      *always* directed exclusively to the primary filesystem. The secondary
      filesystem is never modified.
    - **Read/Check Operations**: These operations first check the primary
      filesystem. If the path is not found, they can *optionally* fall back
      to the secondary filesystem for read-only access.
    - **Controllable Fallback**: The fallback behavior is controlled by the
      `fb_en` property and the `fallback()` context manager,
      allowing for dynamic switching between sandboxed and transparent modes.
    """

    def __init__(self, pri_fs: FileSystem, sec_fs: FileSystem, fb_en: bool = True):
        super().__init__()
        self.primary = pri_fs
        self.secondary = sec_fs
        self._def_fb_en = fb_en
        self._local = threading.local()
        self.name = f"SandboxFS({getattr(pri_fs, 'name', 'primary')}, {getattr(sec_fs, 'name', 'secondary')})"
        logger.debug(f"[{self.name}] Initialized with fb_en={fb_en}")

    @property
    def fb_en(self) -> bool:
        """Controls whether read operations can fall back to the secondary FS."""
        return getattr(self._local, 'fb_en', self._def_fb_en)

    @contextmanager
    def fallback(self, enable: bool):
        """
        A context manager to temporarily change the fallback behavior.
        """
        has = hasattr(self._local, 'fb_en')
        prev = getattr(self._local, 'fb_en', None)
        self._local.fb_en = enable
        
        try:
            yield
        finally:
            if has:
                self._local.fb_en = prev
            else:
                del self._local.fb_en

    @override
    def read_text(self, path: DNSBPath) -> str:
        try:
            return self.primary.read_text(path)
        except (DNSBPathNotFoundError, FileNotFoundError):
            if self.fb_en:
                logger.debug(f"[{self.name}] Fallback read_text for {path}")
                return self.secondary.read_text(path)
            raise

    @override
    def read_bytes(self, path: DNSBPath) -> bytes:
        try:
            return self.primary.read_bytes(path)
        except (DNSBPathNotFoundError, FileNotFoundError):
            if self.fb_en:
                logger.debug(f"[{self.name}] Fallback read_bytes for {path}")
                return self.secondary.read_bytes(path)
            raise

    @override
    def write_text(self, path: DNSBPath, content: str):
        logger.debug(f"[{self.name}] Writing text to primary: {path}")
        self.primary.write_text(path, content)

    @override
    def write_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Writing bytes to primary: {path}")
        self.primary.write_bytes(path, content)

    @override
    def append_text(self, path: DNSBPath, content: str):
        logger.debug(f"[{self.name}] Appending text to primary: {path}")
        self.primary.append_text(path, content)

    @override
    def append_bytes(self, path: DNSBPath, content: bytes):
        logger.debug(f"[{self.name}] Appending bytes to primary: {path}")
        self.primary.append_bytes(path, content)

    @override
    def mkdir(self, path: DNSBPath, parents: bool = False, exist_ok: bool = False):
        logger.debug(f"[{self.name}] Mkdir on primary: {path}")
        self.primary.mkdir(path, parents=parents, exist_ok=exist_ok)

    @override
    def rmtree(self, path: DNSBPath):
        logger.debug(f"[{self.name}] Rmtree on primary: {path}")
        self.primary.rmtree(path)

    @override
    def remove(self, path: DNSBPath):
        logger.debug(f"[{self.name}] Remove on primary: {path}")
        self.primary.remove(path)


    @override
    def exists(self, path: DNSBPath) -> bool:
        if self.primary.exists(path):
            return True
        logger.debug(f"[{self.name}] fb_en={self.fb_en}, exists for {path}")
        return self.fb_en and self.secondary.exists(path)

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        if self.primary.exists(path):
            return self.primary.is_dir(path)
        if self.fb_en:
            logger.debug(f"[{self.name}] fb_en={self.fb_en}, is_dir for {path}")
            return self.secondary.is_dir(path)
        return False

    @override
    def is_file(self, path: DNSBPath) -> bool:
        if self.primary.exists(path):
            return self.primary.is_file(path)
        if self.fb_en:
            logger.debug(f"[{self.name}] fb_en={self.fb_en}, is_file for {path}")
            return self.secondary.is_file(path)
        return False

    @override
    def listdir(self, path: DNSBPath) -> List[DNSBPath]:
        """
        Lists directory contents, merging results from primary and secondary.
        """
        primary_names = set()
        try:
            primary_names.update(p.name for p in self.primary.listdir(path))
        except DNSBPathNotFoundError:
            # If dir doesn't exist in primary, that's fine, we might find it in secondary
            if not self.fb_en or not self.secondary.is_dir(path):
                raise

        if not self.fb_en:
            return [path / name for name in primary_names]
            
        secondary_names = set()
        try:
            secondary_names.update(p.name for p in self.secondary.listdir(path))
        except DNSBPathNotFoundError:
            if not primary_names:
                raise
        all_names = primary_names.union(secondary_names)
        return [path / name for name in sorted(list(all_names))]

    @override
    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        """
        Globs for a pattern, merging results. Primary results shadow secondary.
        """
        results = {str(p): p for p in self.primary.glob(path, pattern)}
        
        if self.fb_en:
            abs_path = self.secondary.absolute(path) if hasattr(self.secondary, 'absolute') else path
            secondary_results = self.secondary.glob(abs_path, pattern)
            for sec_p in secondary_results:
                try:
                    if hasattr(self.secondary, 'relative_to'):
                        rel = self.secondary.relative_to(sec_p, abs_path)
                        primary_equiv = path / rel
                        str_key = str(primary_equiv)
                        if str_key not in results:
                            results[str_key] = primary_equiv
                except (ValueError, InvalidPathError):
                    logger.debug(f"[{self.name}] Skipping secondary path that can't be relativized: {sec_p}")
                    
        return list(results.values())

    @override
    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        """
        Recursively globs for a pattern, merging results. Primary results shadow secondary.
        Returns paths normalized to primary filesystem's structure.
        """
        results = {str(p): p for p in self.primary.rglob(path, pattern)}
        
        if self.fb_en:
            # Get absolute version of path to properly query secondary
            abs_path = self.secondary.absolute(path) if hasattr(self.secondary, 'absolute') else path
            logger.debug(f"[{self.name}] rglob: path={path}, abs_path={abs_path}")
            secondary_results = self.secondary.rglob(abs_path, pattern)
            logger.debug(f"[{self.name}] rglob: found {len(secondary_results)} results from secondary")
            
            # Convert secondary paths to relative paths matching primary structure
            for sec_p in secondary_results:
                try:
                    if hasattr(self.secondary, 'relative_to'):
                        rel = self.secondary.relative_to(sec_p, abs_path)
                        # Reconstruct as primary path
                        primary_equiv = path / rel
                        str_key = str(primary_equiv)
                        if str_key not in results:
                            logger.debug(f"[{self.name}] rglob: mapped {sec_p} -> {primary_equiv}")
                            results[str_key] = primary_equiv
                except (ValueError, InvalidPathError) as e:
                    # If can't make relative, skip this path
                    logger.warning(f"[{self.name}] Failed to relativize path {sec_p} to {abs_path}: {e}")
                except Exception as e:
                    logger.error(f"[{self.name}] Unexpected error processing {sec_p}: {e}")
                    
        return list(results.values())

    @override
    def absolute(self, path: DNSBPath) -> DNSBPath:
        """Returns the absolute path, calculated relative to the primary filesystem."""
        return self.primary.absolute(path)

    @override
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        """Calculates the relative path, assuming the primary filesystem's structure."""
        # Normalize both paths to absolute before delegating
        abs_path = self.absolute(path)
        abs_other = self.absolute(other)
        logger.debug(f"[{self.name}] relative_to: path={path} -> abs={abs_path}, other={other} -> abs={abs_other}")
        return self.primary.relative_to(abs_path, abs_other)

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Gets file status, falling back to secondary if necessary."""
        try:
            return self.primary.stat(path)
        except DNSBPathNotFoundError:
            if self.fb_en:
                return self.secondary.stat(path)
            raise

    @override
    def open(self, path: DNSBPath, mode: str = "rb", **kwargs) -> IO:
        """
        Opens a file. Write modes are restricted to the primary FS.
        Read modes can fall back to the secondary FS.
        """
        is_write_mode = 'w' in mode or 'a' in mode or '+' in mode
        
        if is_write_mode:
            logger.debug(f"[{self.name}] Opening for write on primary: {path}")
            return self.primary.open(path, mode, **kwargs)
        else:
            try:
                return self.primary.open(path, mode, **kwargs)
            except DNSBPathNotFoundError:
                if self.fb_en:
                    logger.debug(f"[{self.name}] Fallback open for read on secondary: {path}")
                    return self.secondary.open(path, mode, **kwargs)
                raise


    @override
    def copy(self, src: DNSBPath, dst: DNSBPath):
        """
        Copies a file. The destination is always in the primary FS.
        The source can be read from either primary or secondary (with fallback).
        """
        logger.debug(f"[{self.name}] Copying {src} -> {dst}")
        content = self.read_bytes(src)
        self.primary.write_bytes(dst, content)

    @override
    def copytree(self, src: DNSBPath, dst: DNSBPath):
        """
        Recursively copies a directory tree. The destination is always in the
        primary FS. The source tree is read as a merged view of primary and
        secondary filesystems.
        """
        logger.debug(f"[{self.name}] Copying tree {src} -> {dst}")
        if not self.is_dir(src):
            raise NotADirectoryError(f"Source path for copytree is not a directory: {src}")

        self.primary.mkdir(dst, parents=True, exist_ok=True)
        
        for item in self.listdir(src):
            src_item_path = src / item.name
            dst_item_path = dst / item.name
            
            if self.is_dir(src_item_path):
                self.copytree(src_item_path, dst_item_path)
            else:
                self.copy(src_item_path, dst_item_path)

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
        super().__init__()
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
        return [self.str2path(p, path) for p in self.fs.ls(self.path2str(path))]

    @override
    def remove(self, path: DNSBPath):
        self.fs.rm(self.path2str(path))

    @override
    def glob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return [self.str2path(p, path) for p in self.fs.glob(self.path2str(path / pattern))]

    @override
    def rglob(self, path: DNSBPath, pattern: str) -> List[DNSBPath]:
        return [self.str2path(p, path) for p in self.fs.glob(self.path2str(path / f"**/{pattern}"))]

    @override
    def open(self, path: DNSBPath, mode: str = "rb", **kwargs) -> IO:
        """Open a file"""
        logger.debug(f"[{self.name}] Opening: {path} with mode '{mode}'")

        if "w" in mode or "a" in mode:
            parent_path_str = self.path2str(path.parent)
            if parent_path_str and parent_path_str != "/":
                self.fs.mkdirs(parent_path_str, exist_ok=True)

        return self.fs.open(self.path2str(path), mode=mode, **kwargs)

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

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        def safe_timestamp(dt_obj):
            if dt_obj is None:
                return epoch.timestamp()
            if isinstance(dt_obj, datetime):
                try:
                    return dt_obj.timestamp()
                except (OSError, ValueError):
                    # Handle invalid datetime objects
                    return epoch.timestamp()
            return epoch.timestamp()
        
        mtime = safe_timestamp(stat_info.get("modified", epoch))
        atime = safe_timestamp(stat_info.get("accessed", epoch))
        ctime = safe_timestamp(stat_info.get("created", epoch))

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
    def path2str(self, path: DNSBPath) -> str:
        return str(self.absolute(path))

    @override
    def absolute(self, path: DNSBPath) -> DNSBPath:
        """Make path absolute. Assumes path is already file:// protocol."""
        if not path.is_disk():
            # Non-disk paths should not reach here after AppFS._resolve_path()
            return path
        if path.is_absolute():
            return path
        
        # Simple file:// to file:// resolution
        return DNSBPath(Path(path.__path__()).absolute())

    @override
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        if not path.is_disk() or not other.is_disk():
            raise UnsupportedFeatureError(
                f"relative_to only supports file protocol, got path={path.protocol}, other={other.protocol}"
            )
        abs_path = self.absolute(path)
        abs_other = self.absolute(other)
        
        try:
            result = Path(str(abs_path)).relative_to(Path(str(abs_other)))
            return DNSBPath(result)
        except ValueError as e:
            raise InvalidPathError(
                f"'{path}' is not relative to '{other}'"
            ) from e

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        """Get file status"""
        return Path(self.path2str(path)).stat()

    @override
    def open(self, path: DNSBPath, mode: str = "rb", **kwargs) -> IO:
        """Open a file"""
        return open(self.path2str(path), mode, **kwargs)

# --------------------
#
# Generic Network FileSystem
#
# --------------------

class NetworkFileSystem(FsspecFileSystem):
    """Network file system using fsspec"""

    def __init__(self, protocol: str):
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

@read_only()
class ResourceFileSystem(FileSystem):
    """
    Resource Protocol FileSystem (Read-Only)
    """

    def __init__(self):
        super().__init__()

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
    
    @override
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        if path.protocol != "resource" or other.protocol != "resource":
            raise UnsupportedFeatureError(
                f"relative_to only supports same protocol, got path={path.protocol}, other={other.protocol}"
            )
        
        from pathlib import PurePosixPath
        try:
            result = PurePosixPath(path.__path__()).relative_to(PurePosixPath(other.__path__()))
            return DNSBPath(
                str(result),
                protocol="resource",
                host="",
                query="",
                fragment=""
            )
        except ValueError as e:
            raise InvalidPathError(f"'{path}' is not relative to '{other}'") from e

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

    @override
    def open(self, path: DNSBPath, mode: str = "rb", **kwargs) -> IO:
        """Open a file - only read modes supported"""
        if 'w' in mode or 'a' in mode or '+' in mode:
            raise ReadOnlyError(f"Cannot write to read-only filesystem: open with mode '{mode}' not allowed")
        logger.debug(f"[ResourceFS] Opening resource: {path} with mode '{mode}'")        
        return self._get_resource_traversable(path).open(mode, **kwargs)

    def copy2fs(self, src: DNSBPath, dst: DNSBPath, fs: FileSystem):
        src_trav = self._get_resource_traversable(src)
        self._copy_to_fs_recursive(src_trav, dst, fs)

    def _copy_to_fs_recursive(
        self,
        src_trav: resources.abc.Traversable,
        dst_path: DNSBPath,
        fs: FileSystem,
    ):
        if src_trav.is_file():
            content = src_trav.read_bytes()
            fs.write_bytes(dst_path, content)
        elif src_trav.is_dir():
            if not fs.exists(dst_path):
                fs.mkdir(dst_path, parents=True, exist_ok=True)

            for item in src_trav.iterdir():
                item_dst_path = dst_path / item.name
                self._copy_to_fs_recursive(item, item_dst_path, fs)



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
    
    @override
    def absolute(self, path: DNSBPath) -> DNSBPath:
        """Return absolute path for memory filesystem"""
        path_str = str(path)
        if not path_str.startswith('/'):
            path_str = '/' + path_str
        return DNSBPath(path_str)

    @override
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        if path.protocol != "file" or other.protocol != "file":
            raise UnsupportedFeatureError(
                f"relative_to only supports same protocol, got path={path.protocol}, other={other.protocol}"
            )
        
        abs_path = self.absolute(path)
        abs_other = self.absolute(other)
        from pathlib import PurePosixPath
        try:
            result = PurePosixPath(str(abs_path)).relative_to(PurePosixPath(str(abs_other)))
            return DNSBPath(str(result))
        except ValueError as e:
            raise InvalidPathError(f"'{path}' is not relative to '{other}'") from e

class HyperMemoryFileSystem(MorefsFileSystem):
    """
    High-performance in-memory filesystem
    """
    def __init__(self, fs_type="mem"):
        super().__init__(fs_type=fs_type)
    
    @override
    def absolute(self, path: DNSBPath) -> DNSBPath:
        """Return absolute path for memory filesystem"""
        path_str = str(path)
        if not path_str.startswith('/'):
            path_str = '/' + path_str
        return DNSBPath(path_str)
    
    @override
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        if path.protocol != "file" or other.protocol != "file":
            raise UnsupportedFeatureError(
                f"relative_to only supports same protocol, got path={path.protocol}, other={other.protocol}"
            )
        
        abs_path = self.absolute(path)
        abs_other = self.absolute(other)
        from pathlib import PurePosixPath
        try:
            result = PurePosixPath(str(abs_path)).relative_to(PurePosixPath(str(abs_other)))
            return DNSBPath(str(result))
        except ValueError as e:
            raise ValueError(f"'{path}' is not relative to '{other}'") from e


# --------------------
#
# Git FileSystem
#
# --------------------

@read_only()
class GitFileSystem(FileSystem):
    """
    A read-only filesystem for accessing files from Git repositories.
    Handles 'git://' URIs, clones repositories into a local cache,
    and allows reading files from specific branches, tags, or commits.
    """

    def __init__(self, cache_fs: FileSystem, cache_root: str = ".dnsb_cache"):
        super().__init__()
        self.cache_fs = cache_fs
        self.cache_root = DNSBPath(cache_root)
        self.name = "GitFS"
        self._synced_repos = set()
        self._repo_locks: Dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        logger.debug(f"[{self.name}] Initialized with cache_root: {self.cache_root}")
        self._init_cache()

    def _init_cache(self):
        """Ensures the cache root directory exists."""
        abs_cache_root = self.cache_fs.absolute(self.cache_root)
        logger.debug(f"[{self.name}] cache_root: {self.cache_root} (absolute: {abs_cache_root})")
        
        if not self.cache_fs.exists(self.cache_root):
            logger.debug(f"[{self.name}] Creating cache directory at '{abs_cache_root}'")
            self.cache_fs.mkdir(self.cache_root, parents=True, exist_ok=True)
        else:
            logger.debug(f"[{self.name}] Cache directory already exists at '{abs_cache_root}'")

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

    def _get_repo_lock(self, repo_url: str) -> threading.Lock:
        """
        Get or create a lock for the given repository URL.
        Thread-safe method to manage per-repository locks.
        """
        with self._locks_lock:
            if repo_url not in self._repo_locks:
                self._repo_locks[repo_url] = threading.Lock()
                logger.debug(f"[{self.name}] Created lock for repository: {repo_url}")
            return self._repo_locks[repo_url]
    
    def _get_local_repo(self, repo_url: str, local_repo_path: DNSBPath) -> git.Repo:
        """Clone repository if not exists, otherwise fetch updates."""
        local_repo_abs = self.cache_fs.absolute(local_repo_path)
        local_repo_str = str(local_repo_abs)
        logger.debug(f"[{self.name}] Local repo path: {local_repo_path} (absolute: {local_repo_abs})")
        
        if not self.cache_fs.exists(local_repo_path):
            logger.debug(f"[{self.name}] Cloning '{repo_url}' to '{local_repo_abs}'...")
            git.Repo.clone_from(repo_url, local_repo_str)
        else:
            logger.debug(f"[{self.name}] Repository '{repo_url}' found in cache at '{local_repo_abs}'")
        
        repo = git.Repo(local_repo_str)
        
        # Try to fetch updates for existing repos
        if self.cache_fs.exists(local_repo_path):
            try:
                repo.remotes.origin.fetch()
            except git.exc.GitCommandError as e:
                logger.warning(f"[{self.name}] Failed to fetch updates for '{repo_url}': {e}. Using cached version.")
        
        return repo
    
    def _should_pull(self, repo: git.Repo, ref: str) -> tuple[bool, str | None]:
        """Determine if ref should be pulled and return (should_pull, branch_name)."""
        if ref == 'HEAD':
            try:
                return True, repo.active_branch.name
            except TypeError:
                logger.debug(f"[{self.name}] HEAD is detached, no pull needed")
                return False, None
        elif ref in repo.heads:
            return True, ref
        else:
            logger.debug(f"[{self.name}] Ref '{ref}' is a tag or commit hash, no pull needed")
            return False, None
    
    def _checkout_and_pull(self, repo: git.Repo, ref: str, repo_url: str):
        """Checkout ref and pull if it's a branch."""
        logger.debug(f"[{self.name}] Checking out ref '{ref}' for '{repo_url}'...")
        
        try:
            repo.git.checkout(ref)
            should_pull, branch_name = self._should_pull(repo, ref)
            
            if should_pull and branch_name:
                logger.debug(f"[{self.name}] Pulling latest changes for branch '{branch_name}'...")
                try:
                    repo.remotes.origin.pull()
                except git.exc.GitCommandError as e:
                    logger.warning(f"[{self.name}] Failed to pull branch '{branch_name}': {e}. Using cached state.")
        
        except git.exc.GitCommandError as e:
            logger.warning(f"[{self.name}] Failed to checkout ref '{ref}': {e}. Falling back to local HEAD.")
            try:
                head_commit = repo.head.commit.hexsha
                repo.git.checkout(head_commit)
                logger.debug(f"[{self.name}] Fallback checkout to HEAD commit '{head_commit}' succeeded.")
            except Exception as e2:
                logger.error(f"[{self.name}] Fallback checkout to local HEAD failed: {e2}")
                raise DNSBPathNotFoundError(
                    f"Ref '{ref}' not found and fallback to HEAD failed in repository '{repo_url}': {e}"
                ) from e

    def _get_synced_repo_path(self, path: DNSBPath) -> DNSBPath:
        """
        Ensures the repository is cloned/updated and at the correct ref.
        Returns the absolute path to the requested file within the cache.
        """
        repo_url, ref, path_in_repo, local_repo_path = self._parse_path(path)
        cache_key = f"{repo_url}@{ref}"
        
        if cache_key not in self._synced_repos:
            repo_lock = self._get_repo_lock(repo_url)
            with repo_lock:
                if cache_key not in self._synced_repos:
                    logger.debug(f"[{self.name}] Syncing repository for '{cache_key}'...")
                    repo = self._get_local_repo(repo_url, local_repo_path)
                    self._checkout_and_pull(repo, ref, repo_url)
                    self._synced_repos.add(cache_key)
                    logger.debug(f"[{self.name}] Sync complete for '{cache_key}'.")
                else:
                    logger.debug(f"[{self.name}] '{cache_key}' was synced by another thread.")
        else:
            logger.debug(f"[{self.name}] '{cache_key}' already synced in this run.")

        final_path = self.cache_fs.absolute(local_repo_path) / path_in_repo
        if not self.cache_fs.exists(final_path):
            raise DNSBPathNotFoundError(
                f"Path '{path_in_repo}' not found in repository '{repo_url}' at ref '{ref}'."
            )
        return final_path

    @override
    def exists(self, path: DNSBPath) -> bool:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.exists(full_path)
        except Exception as e:
            logger.error(f"[{self.name}] Error checking existence for '{path}': {e}")
            return False

    @override
    def relative_to(self, path: DNSBPath, other: DNSBPath) -> DNSBPath:
        if path.protocol != "git" or other.protocol != "git":
            raise UnsupportedFeatureError(
                f"relative_to only supports same protocol, got path={path.protocol}, other={other.protocol}"
            )
        
        if path.host != other.host:
            raise UnsupportedFeatureError(
                f"relative_to across different git hosts: {path.host} vs {other.host}"
            )
        
        synced_path = self._get_synced_repo_path(path)
        synced_other = self._get_synced_repo_path(other)
        return self.cache_fs.relative_to(synced_path, synced_other)

    @override
    def is_dir(self, path: DNSBPath) -> bool:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.is_dir(full_path)
        except Exception as e:
            logger.error(f"[{self.name}] Error in is_dir for '{path}': {e}")
            return False

    @override
    def is_file(self, path: DNSBPath) -> bool:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.is_file(full_path)
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

    @override
    def stat(self, path: DNSBPath) -> os.stat_result:
        try:
            full_path = self._get_synced_repo_path(path)
            return self.cache_fs.stat(full_path)
        except Exception as e:
            logger.error(f"[{self.name}] Error in stat for '{path}': {e}")
            raise

    @override
    def open(self, path: DNSBPath, mode: str = "rb") -> IO:
        """Open a file - not supported for read-only git filesystem"""
        if 'w' in mode or 'a' in mode or '+' in mode:
            self._raise_read_only(path)
        # For read modes, delegate to cache filesystem
        full_path = self._get_synced_repo_path(path)
        return self.cache_fs.open(full_path, mode)

    def copy2fs(self, src: DNSBPath, dst: DNSBPath, fs: FileSystem):
        try:
            full_path = self._get_synced_repo_path(src)
            if isinstance(fs, DiskFileSystem):
                if self.cache_fs.is_dir(full_path):
                    self.cache_fs.copytree(full_path, dst)
                elif self.cache_fs.is_file(full_path):
                    self.cache_fs.copy(full_path, dst)
            else:
                if self.cache_fs.is_dir(full_path):
                    self._copy_directory_to_fs(full_path, dst, fs)
                elif self.cache_fs.is_file(full_path):
                    content = self.cache_fs.read_bytes(full_path)
                    fs.write_bytes(dst, content)
        except Exception as e:
            logger.error(f"[{self.name}] Error in copy2fs for '{src}' to '{dst}': {e}")
            raise

    def _copy_directory_to_fs(self, src_dir: DNSBPath, dst_dir: DNSBPath, fs: FileSystem):
        if not self.cache_fs.exists(src_dir):
            return
        fs.mkdir(dst_dir, parents=True, exist_ok=True)
        for item in self.cache_fs.listdir(src_dir):
            src_item = src_dir / item.name
            dst_item = dst_dir / item.name
            
            if self.cache_fs.is_dir(src_item):
                self._copy_directory_to_fs(src_item, dst_item, fs)
            else:
                try:
                    content = self.cache_fs.read_bytes(src_item)
                    fs.write_bytes(dst_item, content)
                except Exception as e:
                    logger.warning(f"[{self.name}] Failed to copy file {src_item} to {dst_item}: {e}")
                    raise


# --------------------
#
# Helper Functions
#
# --------------------

def create_app_fs(
    use_vfs: bool = False, 
    fb_en: bool = False,
    chroot: DNSBPath = None
) -> "FileSystem":
    """
    Create an AppFileSystem instance with optional VFS, and chroot support.
    
    Args:
        use_vfs: Whether to use virtual file system for 'file' protocol.
                If True, file:// uses HyperMemoryFileSystem instead of DiskFileSystem.
        chroot: Root directory for relative path resolution.
        
    Returns:
        Configured AppFileSystem instance
    """
    app_fs = AppFileSystem(chroot=chroot)
    if use_vfs:
        memfs = HyperMemoryFileSystem()
        backfs = DiskFileSystem()
        sfs = SandboxFileSystem(memfs, backfs, fb_en=fb_en)
        app_fs.register_handler("file", sfs)
    return app_fs
