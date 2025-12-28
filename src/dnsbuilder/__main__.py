"""
DNS Builder - Main entry point

This module provides backward compatibility by delegating to cli.py.
"""

from .cli import cli

if __name__ == "__main__":
    cli()
