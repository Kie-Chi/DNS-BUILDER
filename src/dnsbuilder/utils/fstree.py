"""
File system tree visualization utility.

Provides functions to visualize the structure of a FileSystem.
"""

import logging
from typing import List, Set, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..io import FileSystem, DNSBPath

logger = logging.getLogger(__name__)


def print_tree(
    fs: "FileSystem",
    root: "DNSBPath",
    prefix: str = "",
    is_last: bool = True,
    max_depth: int = -1,
    current_depth: int = 0,
    show_size: bool = False,
    filter_fn: Optional[Callable[["DNSBPath"], bool]] = None,
    visited: Optional[Set[str]] = None
) -> None:
    """
    Print a tree view of the file system structure.
    
    Args:
        fs: FileSystem instance to traverse
        root: Root path to start from
        prefix: Current line prefix (for recursion)
        is_last: Whether this is the last item in current level
        max_depth: Maximum depth to traverse (-1 for unlimited)
        current_depth: Current recursion depth
        show_size: Whether to show file sizes
        filter_fn: Optional filter function to exclude paths
        visited: Set of visited paths (to avoid infinite loops)
    """
    if visited is None:
        visited = set()
    
    # Prevent infinite loops
    path_str = str(root)
    if path_str in visited:
        return
    visited.add(path_str)
    
    # Check max depth
    if max_depth >= 0 and current_depth > max_depth:
        return
    
    # Apply filter
    if filter_fn and not filter_fn(root):
        return
    
    # Check if path exists
    if not fs.exists(root):
        logger.warning(f"Path does not exist: {root}")
        return
    
    # Print current item
    connector = "└── " if is_last else "├── "
    if current_depth == 0:
        connector = ""
        prefix = ""
    
    name = root.__rname__ if hasattr(root, '__rname__') else root.name
    
    # Add size info if requested
    size_info = ""
    if show_size and fs.is_file(root):
        try:
            stat = fs.stat(root)
            size = stat.st_size
            if size < 1024:
                size_info = f" ({size}B)"
            elif size < 1024 * 1024:
                size_info = f" ({size / 1024:.1f}KB)"
            else:
                size_info = f" ({size / (1024 * 1024):.1f}MB)"
        except Exception:
            pass
    
    # Print with appropriate marker
    if fs.is_dir(root):
        logger.debug(f"{prefix}{connector}{name}/{size_info}")
    else:
        logger.debug(f"{prefix}{connector}{name}{size_info}")
    
    # Recurse into directories
    if fs.is_dir(root):
        try:
            children = sorted(fs.listdir(root), key=lambda p: (not fs.is_dir(p), p.name))
            child_count = len(children)
            
            for i, child in enumerate(children):
                is_last_child = (i == child_count - 1)
                
                # Update prefix for children
                if current_depth == 0:
                    child_prefix = ""
                else:
                    child_prefix = prefix + ("    " if is_last else "│   ")
                
                print_tree(
                    fs, child, 
                    prefix=child_prefix,
                    is_last=is_last_child,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    show_size=show_size,
                    filter_fn=filter_fn,
                    visited=visited
                )
        except Exception as e:
            logger.debug(f"Failed to list directory {root}: {e}")


def get_tree_string(
    fs: "FileSystem",
    root: "DNSBPath",
    max_depth: int = -1,
    show_size: bool = False,
    filter_fn: Optional[Callable[["DNSBPath"], bool]] = None
) -> str:
    """
    Get file system tree as a string.
    
    Args:
        fs: FileSystem instance to traverse
        root: Root path to start from
        max_depth: Maximum depth to traverse (-1 for unlimited)
        show_size: Whether to show file sizes
        filter_fn: Optional filter function to exclude paths
    
    Returns:
        String representation of the tree
    """
    import io
    import sys
    
    # Capture print output
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    
    try:
        print_tree(fs, root, max_depth=max_depth, show_size=show_size, filter_fn=filter_fn)
        result = buffer.getvalue()
    finally:
        sys.stdout = old_stdout
    
    return result


def count_files(fs: "FileSystem", root: "DNSBPath", recursive: bool = True) -> dict:
    """
    Count files and directories in a path.
    
    Args:
        fs: FileSystem instance
        root: Root path to count from
        recursive: Whether to count recursively
    
    Returns:
        Dict with 'files' and 'dirs' counts
    """
    if not fs.exists(root) or not fs.is_dir(root):
        return {'files': 0, 'dirs': 0}
    
    counts = {'files': 0, 'dirs': 0}
    
    try:
        for item in fs.listdir(root):
            if fs.is_dir(item):
                counts['dirs'] += 1
                if recursive:
                    sub_counts = count_files(fs, item, recursive=True)
                    counts['files'] += sub_counts['files']
                    counts['dirs'] += sub_counts['dirs']
            else:
                counts['files'] += 1
    except Exception as e:
        logger.debug(f"Failed to count files in {root}: {e}")
    
    return counts


def list_all_files(
    fs: "FileSystem", 
    root: "DNSBPath", 
    pattern: str = None,
    max_depth: int = -1
) -> List["DNSBPath"]:
    """
    List all files recursively.
    
    Args:
        fs: FileSystem instance
        root: Root path to start from
        pattern: Optional glob pattern to filter files
        max_depth: Maximum depth to traverse (-1 for unlimited)
    
    Returns:
        List of all file paths
    """
    if pattern:
        return fs.rglob(root, pattern)
    
    files = []
    
    def _collect(path: DNSBPath, depth: int):
        if max_depth >= 0 and depth > max_depth:
            return
        
        if not fs.exists(path):
            return
        
        if fs.is_file(path):
            files.append(path)
        elif fs.is_dir(path):
            try:
                for item in fs.listdir(path):
                    _collect(item, depth + 1)
            except Exception as e:
                logger.debug(f"Failed to list {path}: {e}")
    
    _collect(root, 0)
    return files
