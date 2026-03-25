"""
DNS Builder Section Definitions

This module contains the Section base class and SectionInfo for DNS software
configuration blocks. Each DNS software can define its own set of supported
configuration blocks with flexible template-based formatting.

Key Features:
1. Template-based block formatting with parameter support
2. Unified content indentation
3. Plugin extensibility through the registry
4. Replaces the old DNS_SOFTWARE_BLOCKS constant

Example:
    # BIND ACL block
    SectionInfo(
        name="acl",
        template='acl "{name}" {{\n{content}\n}};',
        params={"name"}
    )

    # Usage:
    section_info.format_content("192.168.1.0/24;", name="trusted")
    # Result:
    # acl "trusted" {
    #     192.168.1.0/24;
    # };
"""

from abc import ABC, abstractmethod
from typing import Dict, Set, Optional, ClassVar
from dataclasses import dataclass, field
import logging

from . import constants

logger = logging.getLogger(__name__)


@dataclass
class SectionInfo:
    """
    Configuration section/block metadata with template support.

    Attributes:
        name: Block name, e.g., "server", "options", "acl"
        template: Format template with placeholders.
                  Default: "{content}"
                  Examples:
                  - BIND options: "options {{\\n{content}\\n}};"
                  - BIND acl: 'acl "{name}" {{\\n{content}\\n}};'
                  - Unbound server: "server:\\n{content}"
        indent: Number of spaces for content indentation (default: 4)
        params: Set of required parameters (excluding 'content').
                Used for validation.
        repeatable: Whether this block can appear multiple times in config.
                    - False (default): Block can only appear once. Multiple configs
                      must be included inside the block (e.g., BIND options).
                    - True: Block can appear multiple times

    Template Parameters:
        - {content}: Required. The configuration content to wrap
        - Other params: Defined by 'params' field, passed by behavior

    Examples:
        # Simple block without extra params
        >>> info = SectionInfo(name="server", template="server:\\n{content}")
        >>> info.format_content("interface: 0.0.0.0\\nport: 53")
        'server:\\n    interface: 0.0.0.0\\n    port: 53'

        # Block with parameters
        >>> info = SectionInfo(
        ...     name="acl",
        ...     template='acl "{name}" {{\\n{content}\\n}};',
        ...     params={"name"}
        ... )
        >>> info.format_content("192.168.1.0/24;", name="trusted")
        'acl "trusted" {\\n    192.168.1.0/24;\\n};'

        # Repeatable block (Unbound forward-zone)
        >>> info = SectionInfo(
        ...     name="forward-zone",
        ...     template="forward-zone:\\n{content}",
        ...     repeatable=True
        ... )
    """
    name: str
    template: str = "{content}"
    indent: int = 4
    params: Set[str] = field(default_factory=set)
    repeatable: bool = False

    def __post_init__(self):
        """Validate template has {content} placeholder."""
        if "{content}" not in self.template:
            raise ValueError(
                f"SectionInfo template must contain '{{content}}' placeholder. "
                f"Got: {self.template}"
            )

    def format_content(self, content: str, **kwargs) -> str:
        """
        Format configuration content using the template.

        Args:
            content: Configuration content (required)
            **kwargs: Additional template parameters
        """
        # Indent content if multi-line
        if self.indent > 0 and "\n" in content:
            indented = self._indent_content(content)
        else:
            indented = content

        # Merge all parameters
        all_params = {"content": indented, **kwargs}
        missing = self.params - set(kwargs.keys())
        if missing:
            raise ValueError(
                f"Missing required parameters for section '{self.name}': {missing}"
            )

        try:
            return self.template.format(**all_params)
        except KeyError as e:
            raise ValueError(
                f"Template parameter {e} not provided for section '{self.name}'"
            )

    def _indent_content(self, content: str) -> str:
        """Indent multi-line content with configured spaces."""
        lines = []
        for line in content.split("\n"):
            if line.strip():
                lines.append(" " * self.indent + line)
            else:
                lines.append("")
        return "\n".join(lines)

    def get_filename(self, base_name: str = constants.GENERATED_ZONES_FILENAME) -> str:
        """
        Generate the configuration filename for this section.
        Args:
            base_name: Base filename (default: DEFAULT_BASE_NAME)
        """
        if self.name == "global":
            return base_name
        return f"{base_name}.{self.name}"


class Section(ABC):
    """
    Abstract base class for DNS software configuration block definitions.

    Each DNS software inherits from this class to define its supported
    configuration blocks. The Section system provides:

    Example:

        class UnboundSection(Section):
            @classmethod
            def get_sections(cls) -> Dict[str, SectionInfo]:
                return {
                    "global": SectionInfo(name="global"),
                    "server": SectionInfo(
                        name="server",
                        template="server:\\n{content}",
                        indent=4
                    ),
                    "forward-zone": SectionInfo(
                        name="forward-zone",
                        template="forward-zone:\\n{content}",
                        indent=4
                    ),
                }
    """

    # Cache for section info
    _sections_cache: ClassVar[Optional[Dict[str, SectionInfo]]] = None

    @classmethod
    @abstractmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        """
        Return all supported configuration sections for this DNS software.
        """
        pass

    @classmethod
    def get_section(cls, name: str) -> Optional[SectionInfo]:
        """
        Get a specific section by name.

        Args:
            name: Section name
        """
        return cls.get_sections().get(name)

    @classmethod
    def get_section_names(cls) -> Set[str]:
        """
        Get all supported section names.

        Returns:
            Set of section names
        """
        return set(cls.get_sections().keys())

    @classmethod
    def has_section(cls, name: str) -> bool:
        """
        Check if a section is supported.

        Args:
            name: Section name to check
        """
        return name in cls.get_sections()

    @classmethod
    def is_repeatable(cls, name: str) -> bool:
        """
        Check if a section can appear multiple times.

        Args:
            name: Section name to check

        Returns:
            True if the section can repeat, False otherwise
        """
        section_info = cls.get_section(name)
        return section_info.repeatable if section_info else False

    @classmethod
    def get_repeatable_sections(cls) -> Set[str]:
        """
        Get all section names that can appear multiple times.

        Returns:
            Set of repeatable section names
        """
        return {name for name, info in cls.get_sections().items() if info.repeatable}

    @classmethod
    def get_filename(
        cls, section: str, base_name: str = constants.GENERATED_ZONES_FILENAME
    ) -> str:
        """
        Generate filename for a specific section.

        Args:
            section: Section name
            base_name: Base filename
        """
        section_info = cls.get_section(section)
        if section_info:
            return section_info.get_filename(base_name)
        # Fallback for unknown sections
        if section == "global":
            return base_name
        return f"{base_name}.{section}"

    @classmethod
    def format(
        cls, section: str, content: str, **kwargs
    ) -> str:
        """
        Format content for a specific section.

        Args:
            section: Section name
            content: Raw configuration content
            **kwargs: Additional template parameters

        Returns:
            Formatted content with block wrapper if applicable
        """
        section_info = cls.get_section(section)
        if section_info:
            return section_info.format_content(content, **kwargs)
        return content

    @classmethod
    def get_software(cls) -> str:
        """
        Get the software name for this Section class.

        Used by the registry to map software names to Section classes.
        """
        # Extract from class name: BindSection -> bind
        class_name = cls.__name__
        if class_name.endswith("Section"):
            return class_name[:-7].lower()
        return class_name.lower()