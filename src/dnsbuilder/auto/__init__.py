"""
Auto module for DNS Builder automation features.

This module provides automation capabilities for DNS Builder including:
- setup: Pre-build setup scripts
- modify: Configuration modification scripts  
- restrict: Post-build restriction scripts

The module supports both Python and Bash scripts with parallel execution.
"""

from .executor import ScriptExecutor
from .manager import AutomationManager

__all__ = ['ScriptExecutor', 'AutomationManager']