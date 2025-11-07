"""
DNS Builder IO Module

- DNSBPath: Universal path class supporting multiple protocols (file, resource, git, http, etc.)
- pathlib.Path, pathlib.PurePath, pathlib.PurePosixPath, pathlib.PureWindowsPath, pathlib.PosixPath, pathlib.WindowsPath: Standard pathlib classes
- FileSystem: Abstract file system interface
- AppFileSystem: Multi-protocol file system dispatcher
- DiskFileSystem: Local disk file system
- ResourceFileSystem: Read-only access to package resources
- GitFileSystem: Read-only access to Git repositories
- MemoryFileSystem: In-memory file system for testing and HyperMemoryFileSystem: High-performance in-memory file system

Usage:
    from dnsbuilder.io import DNSBPath, AppFileSystem, create_app_fs
    
    fs = create_app_fs(chroot=DNSBPath("/workspace"))
    path = DNSBPath("config.yml")
    content = fs.read_text(path)
"""

from .path import DNSBPath, is_path_absolute, is_path_valid
from .path import Path, PurePath, PurePosixPath, PureWindowsPath, PosixPath, WindowsPath
from .fs import (
    FileSystem,
    AppFileSystem,
    DiskFileSystem,
    ResourceFileSystem,
    GitFileSystem,
    MemoryFileSystem,
    HyperMemoryFileSystem,
    create_app_fs,
)

__all__ = [
    # Path
    'DNSBPath',
    'is_path_absolute',
    'is_path_valid',
    'Path',
    'PurePath',
    'PurePosixPath',
    'PureWindowsPath',
    'PosixPath',
    'WindowsPath',
    # FileSystem
    'FileSystem',
    'AppFileSystem',
    'DiskFileSystem',
    'ResourceFileSystem',
    'GitFileSystem',
    'MemoryFileSystem',
    'HyperMemoryFileSystem',
    'create_app_fs',
]

