"""
File system decorators for error handling and fallback mechanisms.

- Handle IO errors consistently (wrap_io_error)
- Enable fallback to disk when memory operations fail (fallback, fb_read)
- Automatically generate all method delegations from base class (auto)
- Automatically generate all write operations methods that will raise ReadOnlyError (read_only)
"""

import logging
from typing import Tuple, Type, List

from ..exceptions import (
    DNSBPathExistsError,
    DNSBPathNotFoundError,
    DNSBNotAFileError,
    DNSBNotADirectoryError,
)
logger = logging.getLogger(__name__)


def wrap_io_error(func, ignores: Tuple[Type[Exception], ...] = ()):
    """
    Decorator to wrap IO errors into DNS-Builder exceptions.
    
    This decorator catches common file system errors and wraps them
    into DNSBuilder-specific exception types for consistent error handling.

    """
    
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
            if isinstance(e, ignores):
                # Signal exceptions carry the original return value
                val = getattr(e, 'value', None)
                if val is not None:
                    logger.debug(f"Returning {val} from {type(e).__name__} in wrap_io_error")
                    return val
                logger.debug(f"Returning None from {type(e).__name__} in wrap_io_error")
                return None
            raise e
    
    return wrapper

WRITE_METHODS = [
    'write_text', 'write_bytes', 'append_text', 'append_bytes',
    'mkdir', 'rmtree', 'remove', 'copy', 'copytree'
]

def read_only(write_methods=None):
    """
    Class decorator to automatically generate all write operations methods that will raise ReadOnlyError.
    Args:
        write_methods: List of methods to set as read-only, default is all write operations
    """
    if write_methods is None:
        write_methods = WRITE_METHODS
    
    def decorator(cls):
        from ..utils import override
        from ..exceptions import ReadOnlyError
        
        generated_count = 0
        
        for method_name in write_methods:
            if method_name in cls.__dict__:
                logger.debug(f"[ReadOnly] Skipping {method_name} (custom implementation)")
                continue
            
            def make_method(name):
                def method(self, *args, **kwargs):
                    raise ReadOnlyError(f"Cannot write to read-only filesystem: '{name}' not allowed")
                method.__name__ = name
                method.__isabstractmethod__ = False 
                method.__doc__ = f"Raises ReadOnlyError (read-only filesystem)"
                return method
            readonly_method = override(make_method(method_name))
            setattr(cls, method_name, readonly_method)
            
            logger.debug(f"[ReadOnly] Generated read-only method: {method_name}")
            generated_count += 1
        abstracts = set()
        for name in dir(cls):
            try:
                value = getattr(cls, name)
                if getattr(value, "__isabstractmethod__", False):
                    abstracts.add(name)
            except AttributeError:
                pass
        cls.__abstractmethods__ = frozenset(abstracts)
        
        logger.info(f"[ReadOnly] {cls.__name__}: generated {generated_count} read-only methods")
        
        return cls
    
    return decorator
