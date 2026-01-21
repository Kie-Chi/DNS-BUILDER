"""
Auto module for DNS Builder automation features.

- setup: Pre-build setup scripts
- modify: Configuration modification scripts  
- restrict: Post-build restriction scripts
- post: Post-generation scripts (executed after docker-compose.yml is created)

The module supports both Python and Bash scripts with parallel execution.
"""

from .executor import ScriptExecutor
from .manager import AutomationManager

__all__ = ['ScriptExecutor', 'AutomationManager']