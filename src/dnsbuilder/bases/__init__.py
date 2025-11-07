"""
DNS Builder Bases Module

This module contains concrete implementations of Images, Behaviors, and Includers.
Abstract base classes have been moved to abstractions.py.

Concrete implementations:
- Image implementations: BindImage, UnboundImage, PythonImage, JudasImage
- External images: SelfDefinedImage, DockerImage
- Behavior implementations: Bind*Behavior, Unbound*Behavior
- Includer implementations: BindIncluder, UnboundIncluder

Usage:
    from dnsbuilder.bases import BindImage, BindForwardBehavior
"""

from .internal import (
    BindImage,
    UnboundImage,
    PythonImage,
    JudasImage,
)
from .external import (
    SelfDefinedImage,
    DockerImage,
)
from .behaviors import (
    BindMasterBehavior,
    UnboundMasterBehavior,
    BindForwardBehavior,
    UnboundForwardBehavior,
    BindHintBehavior,
    UnboundHintBehavior,
    BindStubBehavior,
    UnboundStubBehavior,
)
from .includers import (
    BindIncluder,
    UnboundIncluder,
)

__all__ = [
    # Internal Images
    'BindImage',
    'UnboundImage',
    'PythonImage',
    'JudasImage',
    # External Images
    'SelfDefinedImage',
    'DockerImage',
    # Behaviors
    'BindMasterBehavior',
    'UnboundMasterBehavior',
    'BindForwardBehavior',
    'UnboundForwardBehavior',
    'BindHintBehavior',
    'UnboundHintBehavior',
    'BindStubBehavior',
    'UnboundStubBehavior',
    # Includers
    'BindIncluder',
    'UnboundIncluder',
]

