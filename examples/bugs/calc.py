#!/usr/bin/env python3
"""
Calculate LoC (Lines of Code) for Docker Compose projects
Excluding specified directories and file types
"""

import os
import fnmatch
from pathlib import Path

# List of patterns to exclude
EXCLUDE_PATTERNS = [
    # Directory exclusions (use **/ to match any location)
    '**/Cpings/**',  # Exclude Cpings directory and its contents at any location
    '**/.git/**',
    '**/__pycache__/**',
    '.git',

    # File type exclusions
    '*.py',
    '*.go',
    '*.pyc',
    '*.pyo',
    '*.so',
    '*.dylib',
    '*.dll',
    '*.a',
    '*.o',
    '*.exe',
    '*.bin',

    # Other binary/generated files
    '*.pdf',
    '*.png',
    '*.jpg',
    '*.jpeg',
    '*.gif',
    '*.svg',
    '*.ico',
    '*.woff',
    '*.woff2',
    '*.ttf',
    '*.eot',
    '*.zip',
    '*.tar',
    '*.gz',
    '*.rar',
]

# Code file extensions to count (whitelist)
INCLUDE_EXTENSIONS = {
    # Configuration files
    '.conf', '.cfg', '.ini', '.yaml', '.yml', '.json', '.xml', '.toml',
    # Shell scripts
    '.sh', '.bash', '.zsh',
    # DNS related
    '.zone', '.zones', '.hints',
    # Network configuration
    '.dockerfile', 'Dockerfile', 'docker-compose',
    # Other text configuration
    '.md', '.txt', '.rst',
    # C/C++ (if needed to keep some)
    # '.c', '.h', '.cpp', '.hpp',
}

# Special filenames (no extension)
INCLUDE_FILES = {
    'Dockerfile',
    'docker-compose.yml',
    'docker-compose.yaml',
}


def should_exclude(filepath: str, base_dir: str) -> bool:
    """Check whether a file should be excluded"""
    rel_path = os.path.relpath(filepath, base_dir)

    for pattern in EXCLUDE_PATTERNS:
        # Handle **/dir/** pattern (directory at any location)
        if pattern.startswith('**/') and pattern.endswith('/**'):
            dir_name = pattern[3:-3]  # Extract directory name, e.g. Cpings
            # Check if the path contains this directory
            parts = rel_path.split(os.sep)
            if dir_name in parts:
                return True
        # Handle dir/** pattern (top-level directory)
        elif pattern.endswith('/**'):
            dir_pattern = pattern[:-3]
            if rel_path.startswith(dir_pattern + os.sep) or rel_path == dir_pattern:
                return True
        # Handle wildcard patterns
        elif fnmatch.fnmatch(rel_path, pattern):
            return True
        # Handle filename matching
        elif fnmatch.fnmatch(os.path.basename(filepath), pattern):
            return True

    return False


def is_text_file(filepath: str) -> bool:
    """Determine whether a file is a text file"""
    # Check extension
    file = Path(filepath)
    exts = file.suffixes

    # Whitelist extensions
    if any(ext in INCLUDE_EXTENSIONS for ext in exts):
        return True

    # Whitelist filenames
    if file.name in INCLUDE_FILES:
        return True

    # Try reading to determine if it's text
    try:
        with open(filepath, 'r', encoding='utf-8', errors='strict') as f:
            f.read(1024)  # Read the first 1KB
        return True
    except (UnicodeDecodeError, PermissionError, OSError):
        return False


def count_loc(filepath: str) -> int:
    """Count the lines of code in a file"""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            return sum(1 for _ in f)
    except (PermissionError, OSError):
        return 0


def analyze_project(project_dir: str) -> dict:
    """Analyze project LoC"""
    result = {
        'total_files': 0,
        'total_loc': 0,
        'by_extension': {},
        'excluded_files': 0,
    }

    for root, dirs, files in os.walk(project_dir):
        # Skip .git directory
        if '.git' in dirs:
            dirs.remove('.git')

        for filename in files:
            filepath = os.path.join(root, filename)

            # Check whether it should be excluded
            if should_exclude(filepath, project_dir):
                result['excluded_files'] += 1
                continue

            # Check whether it is a text file
            if not is_text_file(filepath):
                result['excluded_files'] += 1
                continue

            # Count LoC
            loc = count_loc(filepath)
            if loc > 0:
                result['total_files'] += 1
                result['total_loc'] += loc

                # Categorize by extension
                ext = os.path.splitext(filename)[1].lower() or '(no ext)'
                if ext not in result['by_extension']:
                    result['by_extension'][ext] = {'files': 0, 'loc': 0}
                result['by_extension'][ext]['files'] += 1
                result['by_extension'][ext]['loc'] += loc

    return result


def main():
    # Project directory
    project_dir = Path(__file__).parent / 'output'

    if not project_dir.exists():
        print(f"Error: Project directory not found: {project_dir}")
        return

    print("=" * 60)
    print("LoC Calculator for Docker Compose Project")
    print("=" * 60)
    print(f"\nProject directory: {project_dir}")
    print(f"\nExcluded patterns:")
    for p in EXCLUDE_PATTERNS[:10]:
        print(f"  - {p}")
    print("  ...")

    print("\n" + "-" * 60)
    print("Analyzing...")
    print("-" * 60 + "\n")

    # Iterate over subdirectories under output
    for subdir in sorted(project_dir.iterdir()):
        if subdir.is_dir():
            print(f"\n{'=' * 60}")
            print(f"Project: {subdir.name}")
            print("=" * 60)

            result = analyze_project(str(subdir))

            print(f"\nTotal Files: {result['total_files']}")
            print(f"Total LoC:   {result['total_loc']}")
            print(f"Excluded:     {result['excluded_files']} files")

            if result['by_extension']:
                print("\nBy Extension:")
                print(f"{'Extension':<15} {'Files':>8} {'LoC':>10}")
                print("-" * 35)
                for ext, stats in sorted(result['by_extension'].items(),
                                         key=lambda x: x[1]['loc'], reverse=True):
                    print(f"{ext:<15} {stats['files']:>8} {stats['loc']:>10}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == '__main__':
    main()