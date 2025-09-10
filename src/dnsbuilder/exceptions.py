class DNSBuilderError(Exception):
    """Base exception for all application-specific errors."""
    pass

class ConfigError(DNSBuilderError):
    """Errors related to configuration validation."""
    pass

class CircularDependencyError(ConfigError):
    """Raised when a circular dependency is detected in configs."""
    pass

class BuildError(DNSBuilderError):
    """Errors occurring during the build process."""
    pass

class PathError(ConfigError):
    """Errors related to path resolution."""
    pass

class VolumeNotFoundError(PathError):
    """Raised when a source path for a volume does not exist."""
    pass

class BehaviorError(BuildError):
    """Raised for issues related to behavior processing."""
    pass

class ImageError(DNSBuilderError):
    """Errors related to image definition or creation."""
    pass
