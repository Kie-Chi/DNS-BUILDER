"""Zone name utilities for DNS operations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ZoneName:
    """
    Unified zone name handling for DNS operations.

    Supports both FQDN (Fully Qualified Domain Name) and label formats.
    Automatically normalizes input to standard formats.

    Examples:
        >>> ZoneName("example.com")
        ZoneName(fqdn='example.com.', label='example.com')
        >>> ZoneName("example.com.")
        ZoneName(fqdn='example.com.', label='example.com')
        >>> ZoneName(".")
        ZoneName(fqdn='.', label='root')
        >>> ZoneName("root")
        ZoneName(fqdn='.', label='root')
    """

    fqdn: str
    label: str

    def __init__(self, name: str):
        """
        Create a ZoneName from any format.

        Args:
            name: Zone name in any format:
                - FQDN: "example.com.", "."
                - Label: "example.com", "root"
        """
        fqdn = self._normalize(name)
        label = "root" if fqdn == "." else fqdn.rstrip(".")
        object.__setattr__(self, "fqdn", fqdn)
        object.__setattr__(self, "label", label)

    @property
    def is_root(self) -> bool:
        """Check if this is the root zone."""
        return self.fqdn == "."

    @property
    def filename(self) -> str:
        """Get the base filename for this zone (e.g., 'db.example.com')."""
        return f"db.{self.label}"

    @staticmethod
    def _normalize(name: str) -> str:
        """
        Normalize a zone name to FQDN format.

        Args:
            name: Zone name in any format

        Returns:
            FQDN format (e.g., "example.com.", ".")
        """
        name = name.strip()
        if name in (".", "root", ""):
            return "."
        return name.rstrip(".") + "."

    def __str__(self) -> str:
        return self.fqdn

    def __repr__(self) -> str:
        return f"ZoneName(fqdn='{self.fqdn}', label='{self.label}')"