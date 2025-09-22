# DNSBuilder\src\dnsbuilder\io\path.py

import logging
from typing import override
from pathlib import PurePosixPath, PureWindowsPath, Path, PurePath
from urllib.parse import urlparse
from .. import constants
from ..exceptions import InvalidPathError


logger = logging.getLogger(__name__)


def add_protocol_checkers(cls):
    """
    Class Decorator to add is_protocol for cls
    """

    def create_checker(protocol_name):
        def checker(self):
            return getattr(self, "protocol", None) == protocol_name

        checker.__name__ = f"is_{protocol_name}"
        return checker

    for protocol in constants.KNOWN_PROTOCOLS:
        method_name = f"is_{protocol}"
        checker_method = create_checker(protocol)
        setattr(cls, method_name, method_name)
        setattr(cls, method_name, checker_method)
    return cls


@add_protocol_checkers
class DNSBPath(PurePosixPath):
    """
    It can represent both local file paths and URLs, automatically parsing
    them to provide protocol and host information. 
    """

    def __new__(cls, *args, **kwargs):
        if not args:
            return super().__new__(cls)

        is_origin = kwargs.pop("is_origin", False)
        protocol_kw = kwargs.pop("protocol", None)
        host_kw = kwargs.pop("host", None)
        query_kw = kwargs.pop("query", None)
        fragment_kw = kwargs.pop("fragment", None)

        # Protocol and host are passed explicitly, so we skip parsing.
        __first_part = args[0]
        if protocol_kw is not None:
            obj = super().__new__(cls, *args, **kwargs)
            obj.protocol = protocol_kw
            obj.host = host_kw if host_kw is not None else ""
            obj.query_str = query_kw if query_kw is not None else ""
            obj.fragment = fragment_kw if fragment_kw is not None else ""
        else:
            path_str = str(args[0])
            parsed = urlparse(path_str)

            if parsed.scheme in constants.KNOWN_PROTOCOLS:
                obj_protocol = parsed.scheme
                obj_host = parsed.netloc
                path_part = parsed.path
                obj_query = parsed.query
                obj_fragment = parsed.fragment
            else:
                obj_protocol = "file"
                obj_host = ""
                # help to convert windows path to posix path
                path_part = PurePath(path_str).as_posix()
                obj_query = ""
                obj_fragment = ""

            obj = super().__new__(cls, path_part, *(args[1:]), **kwargs)
            obj.protocol = obj_protocol
            obj.host = obj_host
            obj.query_str = obj_query
            obj.fragment = obj_fragment
            __first_part = path_part

        obj.is_origin = is_origin
        obj.__first_part = __first_part
        return obj

    def _reconstruct(self, new_path_part: PurePosixPath) -> "DNSBPath":
        """
        Internal helper to create a new DNSBPath. Crucially, it passes the
        """
        if hasattr(new_path_part, '__path__'):
            path_str = new_path_part.__path__()
        else:
            path_str = str(new_path_part)
            
        return DNSBPath(
            path_str,
            is_origin=self.is_origin,
            protocol=self.protocol,
            host=self.host,
            query=self.query_str,
            fragment=self.fragment,
        )
    
    def __init__(self, *args, **kwargs):
        kwargs.pop("is_origin", None)
        kwargs.pop("protocol", None)
        kwargs.pop("host", None)
        kwargs.pop("query", None)
        kwargs.pop("fragment", None)
        super().__init__(self.__first_part, *(args[1:]), **kwargs)

    @property
    @override
    def parent(self):
        return self._reconstruct(super().parent)

    @override
    def joinpath(self, *args):
        return self._reconstruct(super().joinpath(*args))

    @override
    def __truediv__(self, other):
        return self._reconstruct(super().joinpath(other))

    @override
    def __rtruediv__(self, other):
        if self.is_absolute():
            raise InvalidPathError(
                "Can not join absolute path with relative path, like path + /path"
            )
        return self._reconstruct(super().__rtruediv__(other))

    @property
    def need_copy(self) -> bool:
        if self.is_origin:
            return False
        if self.protocol != "file":
            return True
        return not self.is_absolute()

    @property
    def need_check(self) -> bool:
        if self.is_origin:
            return False
        return True

    @override
    def __str__(self) -> str:
        """
        Return the string representation of the path, reconstructing the full URI.
        """
        path_part = super().__str__()

        if self.protocol == "file":
            return path_part

        if self.protocol == "resource":
            return f"resource:{path_part}"

        # For other URL-like protocols
        host_part = f"//{self.host}" if self.host else ""
        query_part = f"?{self.query_str}" if self.query_str else ""
        fragment_part = f"#{self.fragment}" if self.fragment else ""
        return f"{self.protocol}:{host_part}{path_part}{query_part}{fragment_part}"
    
    def __path__(self) -> str:
        return super().__str__()

    @property
    def query(self) -> dict:
        if not hasattr(self, "_query_dict"):
            from urllib.parse import parse_qs
            self._query_dict = parse_qs(self.query_str)
        return self._query_dict

    @override
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}('{self}')"
    
    @override
    def is_absolute(self) -> bool:
        """
        Return True if the path is absolute.
        For URLs, the path part must be absolute (start with /).
        """
        return is_path_absolute(self.__path__())

def is_path_valid(path: str) -> bool:
    """
    Check if a path is valid.
    """
    is_windows = False
    is_posix = False
    try:
        PureWindowsPath(path)
        is_windows = True
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise InvalidPathError(f"Path is invalid: {path}")
    try:
        PurePosixPath(path)
        is_posix = True
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise InvalidPathError(f"Path is invalid: {path}")
    return is_windows or is_posix


def is_path_absolute(path: str) -> bool:
    """
    Check if a path is absolute.
    """
    is_absolute = False
    try:
        is_absolute = PurePosixPath(path).is_absolute()
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise InvalidPathError(f"Path is invalid: {path}")
    if is_absolute:
        return True
    try:
        return PureWindowsPath(path).is_absolute()
    except (ValueError, TypeError, OSError):
        pass
    except Exception:
        raise InvalidPathError(f"Path is invalid: {path}")