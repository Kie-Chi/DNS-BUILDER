"""
File system decorators for error handling and fallback mechanisms.

- Handle IO errors consistently (wrap_io_error)
- Enable fallback to disk when memory operations fail (fallback, fb_read)
- Automatically generate all method delegations from base class (auto)
- Automatically generate all write operations methods that will raise ReadOnlyError (read_only)
"""

import functools
from gc import enable
import logging
from typing import Tuple, Type, List

from ..exceptions import (
    DNSBPathExistsError,
    DNSBPathNotFoundError,
    DNSBNotAFileError,
    DNSBNotADirectoryError,
    Signal,
    SignalPathNotFound
)
logger = logging.getLogger(__name__)


def wrap_io_error(func, ignores: Tuple[Type[Exception], ...] = (Signal,)):
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

def signal(sig: Signal):
    """
    Decorator to raise a Signal when function return result Not True
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, path, *args, **kwargs):
            try:
                res = func(self, path, *args, **kwargs)
            except Exception as e:
                raise e
            if not res:
                # Check if fallback is enabled
                # The enable_fallback state is synced from AppFileSystem to handler
                _fallback = getattr(self, '_fallback', None)
                enable_fallback = _fallback.enable if _fallback else False
                
                if enable_fallback:
                    logger.debug(f"[{self.__class__.__name__}] Signal {sig.__name__} triggered for path: {path}")
                    raise sig(f"[{self.__class__.__name__}] Signal {sig.__name__} triggered for path: {path}", value=res)
                else:
                    logger.debug(f"[DISABLED {self.__class__.__name__}] Signal {sig.__name__} suppressed for path: {path}")
            return res
        return wrapper
    return decorator

def fallback(errors: Tuple[Type[Exception], ...] = (FileNotFoundError, KeyError)):
    """
    Decorator to enable fallback mechanism for file system operations.
    
    Args:
        errors: Tuple of exception types that should trigger fallback.
                Default is (FileNotFoundError, KeyError).
    
    Usage:

        @fallback(errors=(FileNotFoundError, KeyError))
        def read_text(self, path: DNSBPath) -> str:
            return AppFileSystem._delegator("read_text")(self, path)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, path, *args, **kwargs):
            # Import here to avoid circular dependency
            from .path import DNSBPath
            
            try:
                return func(self, path, *args, **kwargs)
            except errors as e:
                # Check if fallback is enabled and applicable
                _fallback = getattr(self, '_fallback', None)
                if not _fallback or not _fallback.enable:
                    raise
                if not isinstance(path, DNSBPath) or path.protocol != "file":
                    raise
                if not hasattr(self, '_fallback_handler') or not self._fallback_handler:
                    raise
                
                method_name = func.__name__
                logger.debug(
                    f"[Fallback] Primary handler failed for {path} ({method_name}), "
                    f"trying fallback: {type(e).__name__}"
                )
                
                # Try fallback handler
                fallback_method = getattr(self._fallback_handler, method_name, None)
                if not fallback_method:
                    logger.debug(f"[Fallback] Fallback handler has no method '{method_name}'")
                    raise
                
                try:
                    result = fallback_method(path, *args, **kwargs)
                    
                    if hasattr(self, '_record_fallback'):
                        self._record_fallback(path, method_name)
                    logger.debug(
                        f"[Fallback] Successfully read from disk via fallback: {path} ({method_name})"
                    )
                    return result
                except Exception as fallback_e:
                    logger.debug(
                        f"[Fallback] Fallback handler also failed for {path}: "
                        f"{type(fallback_e).__name__}"
                    )
                    # Raise the original exception, not the fallback exception
                    raise e
        
        return wrapper
    return decorator


# Read operations: allow fallback on FileNotFoundError and KeyError
fb_read = fallback(errors=(FileNotFoundError, KeyError))

# Check operations: same as read (exists, is_file, is_dir)
fb_check = fallback(errors=(FileNotFoundError, KeyError, SignalPathNotFound))


def _infer_fb(method_name: str) -> str:
    """
    Infer the fallback type for a method.
    """
    # read operations
    if method_name.startswith('read') or method_name in ['open', 'stat']:
        return 'read'
    
    # check operations (including path operations)
    if (method_name.startswith('is_') or 
        method_name in ['exists', 'listdir', 'glob', 'rglob', 'absolute', 'relative_to']):
        return 'check'
    
    if (method_name.startswith('write') or 
        method_name.startswith('append') or
        method_name in ['mkdir', 'remove', 'rmtree']):
        return None
    
    logger.debug(f"Unknown method type for {method_name}, defaulting to no fallback")
    return None


def auto(fallback_overrides=None):
    """
    Class decorator to automatically generate all method delegations from base class.
    
    Args:
        fallback_overrides: Dictionary to override the inferred fallback type.
            Format: {'method_name': 'read'/'check'/None}
    """
    if fallback_overrides is None:
        fallback_overrides = {}
    
    def decorator(cls):
        import inspect
        try:
            from ..utils import override
        except ImportError:
            def override(func):
                return func
        base_class = cls.__bases__[0]
        all_methods = []
        for name, method in inspect.getmembers(base_class, predicate=inspect.isfunction):
            if name.startswith('_'):
                continue
            try:
                if isinstance(inspect.getattr_static(base_class, name), (classmethod, staticmethod)):
                    continue
            except AttributeError:
                pass
            all_methods.append(name)
        
        logger.debug(f"[Delegate] Found {len(all_methods)} public methods in {base_class.__name__}")
        generated_count = 0
        skipped_count = 0
        for method_name in all_methods:
            if method_name in cls.__dict__:
                logger.debug(f"[Delegate] Skipping {method_name} (custom implementation)")
                skipped_count += 1
                continue
            
            if method_name in fallback_overrides:
                fallback_type = fallback_overrides[method_name]
                logger.debug(f"[Delegate] Using override for {method_name}: {fallback_type}")
            else:
                fallback_type = _infer_fb(method_name)
            
            base_method = getattr(base_class, method_name)
            try:
                sig = inspect.signature(base_method)
            except (ValueError, TypeError):
                sig = None
            
            def make_method(name, fb_type, signature, base_meth):
                def method(self, *args, **kwargs):
                    return type(self)._delegator(name)(self, *args, **kwargs)
                
                method.__name__ = name
                if signature:
                    method.__signature__ = signature
                if base_meth.__doc__:
                    method.__doc__ = base_meth.__doc__                
                method.__isabstractmethod__ = False
                
                if fb_type == 'read':
                    method = fb_read(method)
                elif fb_type == 'check':
                    method = fb_check(method)
                
                method = wrap_io_error(method)
                method = override(method)
                
                return method
            generated_method = make_method(method_name, fallback_type, sig, base_method)
            setattr(cls, method_name, generated_method)
            getattr(cls, method_name).__isabstractmethod__ = False
            
            logger.debug(f"[Delegate] Generated {method_name} with fallback={fallback_type}")
            generated_count += 1
        
        logger.info(
            f"[Delegate] {cls.__name__}: "
            f"generated {generated_count} methods, "
            f"skipped {skipped_count} custom implementations"
        )
        abstracts = set()
        for name in dir(cls):
            try:
                value = getattr(cls, name)
                if getattr(value, "__isabstractmethod__", False):
                    abstracts.add(name)
            except AttributeError:
                pass
        cls.__abstractmethods__ = frozenset(abstracts)
        logger.debug(f"[Delegate] Updated __abstractmethods__: {cls.__abstractmethods__}")
        return cls
    
    return decorator

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
