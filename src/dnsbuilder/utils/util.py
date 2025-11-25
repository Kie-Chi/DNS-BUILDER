"""
Some utils for DNSBuilder
"""

from typing import List, Optional
from ..exceptions import UnsupportedFeatureError
import re

# ----------------------
#
#  Name Converting
#
# ----------------------

s_pattern = re.compile(r'^[a-z0-9]+(_[a-z0-9]+)*$')
cpn = re.compile(r'(?<!^)(?=[A-Z])')
cp_pattern = re.compile(r'^[a-zA-Z][a-zA-Z0-9]*$')

def to_snake(name: str) -> str:
    """
    Convert camalCase or PascalCase to snake_case
    """
    if not cp_pattern.fullmatch(name):
        raise UnsupportedFeatureError(f"Only PascalCase and camelCase can use to_snake, but '{name}' got.")
    return cpn.sub('_', name).lower()


def to_pascal(name: str) -> str:
    """
    Convert snake_case to PascalCase
    """
    if not s_pattern.fullmatch(name):
        raise UnsupportedFeatureError(f"Only snake_case can use to_pascal, but '{name}' got.")
    return "".join([_s.capitalize() for _s in name.split('_')])


def to_camel(name: str) -> str:
    """
    Convert snake_case to camelCase
    """
    if not s_pattern.fullmatch(name):
        raise UnsupportedFeatureError(f"Only snake_case can use to_camel, but '{name}' got.")
    return "".join([_s.capitalize() if i != 0 else _s for i, _s in enumerate(name.split('_'))])
