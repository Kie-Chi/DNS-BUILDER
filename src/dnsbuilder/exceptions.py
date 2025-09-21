class DNSBuilderError(Exception):
    """Base exception for all application-specific errors."""

    pass


# --- 1. Errors related to loading and parsing the configuration file ---
class ConfigurationError(DNSBuilderError):
    """Base class for errors encountered while finding, reading, or parsing config files."""

    pass


class ConfigFileMissingError(ConfigurationError):
    """Raised when the main configuration file cannot be found."""

    pass


class ConfigParsingError(ConfigurationError):
    """Raised when a YAML configuration file is syntactically incorrect."""

    pass


class ConfigValidationError(ConfigurationError):
    """Raised when the configuration fails structural validation (e.g., Pydantic)."""

    pass


# --- 2. Errors related to the logical validity and definitions within the config ---
class DefinitionError(DNSBuilderError):
    """Base class for errors in the logical definition and references within the config."""

    pass


class CircularDependencyError(DefinitionError):
    """Raised when a circular dependency is detected in image or build definitions."""

    pass


class ReferenceNotFoundError(DefinitionError):
    """Raised when a 'ref' points to a non-existent image or build definition."""

    pass


class ImageDefinitionError(DefinitionError):
    """Raised for logical errors in an 'images' block, like conflicting keys or invalid versions."""

    pass

class BuildDefinitionError(DefinitionError):
    """Raised for errors in build definitions, like using invalid template"""

    pass


class NetworkDefinitionError(DefinitionError):
    """Raised for errors in network planning, such as an invalid static IP."""

    pass


# --- 3. Errors that occur during the artifact generation (build) phase ---
class BuildError(DNSBuilderError):
    """Base class for errors that occur during the generation of output artifacts."""

    pass


class VolumeError(BuildError):
    """Raised for issues with volume processing, such as a missing source path."""

    pass


class BehaviorError(BuildError):
    """Raised for issues related to DNS behavior processing."""

    pass


class UnsupportedFeatureError(BuildError):
    """Raised when a requested feature is not implemented."""

    pass


# --- 4. Errors related to IO operations ---
class DNSBIOError(DNSBuilderError):
    """Base class for IO-related errors."""

    pass


class InvalidPathError(DNSBIOError):
    """Raised when a path is invalid."""

    pass


class ProtocolError(DNSBIOError, UnsupportedFeatureError):
    """Raised when an unsupported protocol is used."""

    pass

 
class ReadOnlyError(DNSBIOError):
    """Raised when a write operation is attempted on a read-only filesystem."""

    pass


class DNSBPathExistsError(DNSBIOError):
    """Raised when a file or directory already exists."""

    pass


class DNSBPathNotFoundError(DNSBIOError):
    """Raised when a file or directory is not found."""

    pass


class DNSBNotAFileError(DNSBIOError):
    """Raised when a file is expected, but a directory is found."""

    pass


class DNSBNotADirectoryError(DNSBIOError):
    """Raised when a directory is expected, but a file is found."""

    pass

# --- 5. Errors related to the UNKOWN ---
class UnknownError(DNSBuilderError, UnsupportedFeatureError):
    """Raised when an unknown error occurs."""

    pass
