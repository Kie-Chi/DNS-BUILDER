"""Zone utilities for DNS operations."""

from dataclasses import dataclass
from typing import Optional, Tuple


ZONE_ATTRIBUTE = (
    "parts",
    "is_root",
    "fqdn",
    "label",
    "filename",
    "name",
    "parent",
    "is_subdomain_of",
    "is_parent_of",
)

@dataclass(frozen=True)
class Zone:
    """
    Unified zone handling for DNS operations.

    Stores domain as parts (labels from left to right).
    Derives FQDN and label formats on demand.

    Examples:
        >>> zone = Zone("example.com")
        >>> zone.fqdn
        'example.com.'
        >>> zone.label
        'example.com'
        >>> zone.parts
        ('example', 'com')

        >>> Zone(".")
        Zone(parts=())
        >>> Zone(".").is_root
        True

        >>> zone = Zone("example.com")
        >>> (zone / "www").fqdn
        'www.example.com.'
        >>> (zone / "www" / "api").fqdn
        'api.www.example.com.'


        >>> Zone("www.example.com").parent.fqdn
        'example.com.'

        >>> Zone("www.example.com").name
        'www'

        >>> zone = Zone("example.com")
        >>> zone.www.fqdn
        'www.example.com.'
    """

    parts: Tuple[str, ...]

    def __init__(self, name: str):
        """
        Create a Zone from any format.

        Args:
            name: Zone name in any format:
                - FQDN: "example.com.", "."
                - Label: "example.com", "root"
        """
        parts = self._parse(name)
        object.__setattr__(self, "parts", parts)

    @property
    def is_root(self) -> bool:
        """Check if this is the root zone."""
        return len(self.parts) == 0

    @property
    def fqdn(self) -> str:
        """Get FQDN format (e.g., 'example.com.', '.' for root)."""
        if self.is_root:
            return "."
        return ".".join(self.parts) + "."

    @property
    def label(self) -> str:
        """Get label format (e.g., 'example.com', 'root' for root)."""
        if self.is_root:
            return "root"
        return ".".join(self.parts)

    @property
    def filename(self) -> str:
        """Get the base filename for this zone (e.g., 'db.example.com')."""
        return f"db.{self.label}"

    @property
    def name(self) -> str:
        """
        Get the leftmost label of the zone name.

        Examples:
            >>> Zone("www.example.com").name
            'www'
            >>> Zone("com").name
            'com'
            >>> Zone(".").name
            ''
        """
        if self.is_root:
            return ""
        return self.parts[0]

    @property
    def parent(self) -> Optional["Zone"]:
        """
        Get the parent zone.

        Examples:
            >>> Zone("www.example.com").parent.fqdn
            'example.com.'
            >>> Zone("com").parent.fqdn
            '.'
            >>> Zone(".").parent
            None
        """
        if self.is_root:
            return None

        if len(self.parts) == 1:
            # TLD's parent is root
            return Zone(".")

        # Remove the leftmost part
        return Zone.from_parts(self.parts[1:])

    def join(self, subdomain: str) -> "Zone":
        """
        Create a subdomain by prepending a label.

        Args:
            subdomain: Label to prepend (e.g., "www")

        Examples:
            >>> Zone("example.com").join("www").fqdn
            'www.example.com.'
        """
        subdomain = subdomain.strip().rstrip(".")
        if not subdomain:
            return self

        if self.is_root:
            return Zone(subdomain)

        return Zone(f"{subdomain}.{self.label}")

    @classmethod
    def from_parts(cls, parts: Tuple[str, ...]) -> "Zone":
        """
        Create a Zone from parts tuple.

        Args:
            parts: Tuple of labels from left to right

        Examples:
            >>> Zone.from_parts(("www", "example", "com")).fqdn
            'www.example.com.'
            >>> Zone.from_parts(()).is_root
            True
        """
        zone = object.__new__(cls)
        object.__setattr__(zone, "parts", parts)
        return zone

    def __truediv__(self, subdomain: str) -> "Zone":
        """
        Support / operator for creating subdomains.

        Unlike pathlib.Path which appends to the right,
        DNS zones prepend to the left (subdomain.parentzone).

        Examples:
            >>> Zone("example.com") / "www"
            Zone(parts=('www', 'example', 'com'))
        """
        return self.join(subdomain)

    def __getattr__(self, name: str) -> "Zone":
        """
        Support attribute access for creating subdomains.

        This only works for valid DNS labels (alphanumeric and hyphen).

        Examples:
            >>> Zone("example.com").www.fqdn
            'www.example.com.'
        """
        # Allow dataclass attributes to work normally
        if name.startswith("_") or name in ZONE_ATTRIBUTE:
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Validate it's a valid DNS label
        if not name:
            raise AttributeError("Empty subdomain")

        # Allow alphanumeric and hyphen (valid DNS label characters)
        if not all(c.isalnum() or c == "-" for c in name):
            raise AttributeError(f"Invalid DNS label: '{name}'")

        return self.join(name)

    @staticmethod
    def _parse(name: str) -> Tuple[str, ...]:
        """
        Parse a zone name into parts.

        Args:
            name: Zone name in any format
        """
        name = name.strip()
        # Handle root zone variants (including multiple dots like ".....")
        if not name or name == "root" or all(c == "." for c in name):
            return ()

        # Remove trailing dots and split
        name = name.strip(".")
        if not name:
            return ()
        return tuple(name.split("."))

    def __str__(self) -> str:
        return self.fqdn

    def __repr__(self) -> str:
        return f"Zone(parts={self.parts})"

    def __eq__(self, other) -> bool:
        if isinstance(other, Zone):
            return self.parts == other.parts
        if isinstance(other, str):
            return self.parts == self._parse(other)
        return False

    def __hash__(self) -> int:
        return hash(self.parts)

    def is_subdomain_of(self, other: "Zone | str") -> bool:
        """
        Check if this zone is a subdomain of another zone.

        Args:
            other: Zone or zone name string to check against

        Examples:
            >>> Zone("www.example.com").is_subdomain_of("example.com")
            True
            >>> Zone("api.www.example.com").is_subdomain_of("example.com")
            True
            >>> Zone("example.com").is_subdomain_of("example.com")
            False
            >>> Zone("other.com").is_subdomain_of("example.com")
            False
            >>> Zone("example.com").is_subdomain_of(".")
            True
        """
        if isinstance(other, str):
            other = Zone(other)
        if other.is_root:
            return not self.is_root
        if len(self.parts) <= len(other.parts):
            return False

        # Check if self.parts ends with other.parts
        return self.parts[-len(other.parts):] == other.parts

    def is_parent_of(self, other: "Zone | str") -> bool:
        """
        Check if this zone is a parent of another zone.

        Args:
            other: Zone or zone name string to check against
        Examples:
            >>> Zone("example.com").is_parent_of("www.example.com")
            True
            >>> Zone(".").is_parent_of("example.com")
            True
            >>> Zone("example.com").is_parent_of("example.com")
            False
        """
        if isinstance(other, str):
            other = Zone(other)
        return other.is_subdomain_of(self)

    def __len__(self) -> int:
        """Return the number of labels in the zone name."""
        return len(self.parts)

    def __getitem__(self, index):
        """Access parts by index."""
        return self.parts[index]


# Backward compatibility alias
ZoneName = Zone