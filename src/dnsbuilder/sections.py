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
5. Auto-generated wrap_re for block location in Includer

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

    # Auto-generated wrap_re:
    section_info.wrap_re  # Returns: r'acl\\s+"[^"]*\\s*\\{'
"""

from abc import ABC, abstractmethod
from typing import Dict, Set, Optional, ClassVar
from dataclasses import dataclass, field
import re
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
        wrap_re: Regex pattern to locate this block in config file.
                 Auto-generated from template if not provided.
                 Used by Includer to find where to inject includes.

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

        # Auto-generated wrap_re
        >>> info = SectionInfo(name="options", template="options {{\\n{content}\\n}};")
        >>> info.wrap_re
        'options\\\\s*\\\\{'
    """
    name: str
    template: str = "{content}"
    indent: int = 4
    params: Set[str] = field(default_factory=set)
    repeatable: bool = False
    wrap_re: Optional[str] = None
    _generated_wrap_re: str = field(default="", init=False, repr=False)

    def __post_init__(self):
        """Validate template has {content} placeholder and generate wrap_re."""
        if "{content}" not in self.template:
            raise ValueError(
                f"SectionInfo template must contain '{{content}}' placeholder. "
                f"Got: {self.template}"
            )

        # Auto-generate wrap_re if not provided
        if self.wrap_re is None:
            self._generated_wrap_re = self._derive_wrap_re()
        else:
            self._generated_wrap_re = self.wrap_re

    @property
    def block_pattern(self) -> Optional[str]:
        """
        Get the regex pattern to locate this block in config.

        Returns None for global section (no block to locate).
        Returns the wrap_re for other sections.
        """
        if self.name == "global":
            return None
        return self._generated_wrap_re

    def _derive_wrap_re(self) -> str:
        r"""
        Auto-generate wrap_re from template.
        Examples:

            "options {{\n{content}\n}};" -> r'options\s*\{'
            'acl "{name}" {{\n{content}\n}};' -> r'acl\s+"[^"]*"\s*\{'
            "server:\n{content}" -> r'server\s*:'
            "{content}" -> "" (global section)
        """
        if self.name == "global":
            return ""

        # Find {content} position
        content_pos = self.template.find("{content}")
        if content_pos == -1:
            return ""

        # Extract header (everything before {content})
        header = self.template[:content_pos]

        # Clean up and convert to regex
        return self._header_to_regex(header)

    def _header_to_regex(self, header: str) -> str:
        r"""
        Convert template header to regex pattern for block location.

        Handles:
        - Parameter placeholders: {name} -> [^"]* or \S+
        - Escaped braces: {{ -> \{
        - Whitespace normalization
        - Special character escaping

        Args:
            header: The template portion before {content}
        """
        if not header:
            return ""

        result = header
        result = result.replace("{{", "\x00BRACE\x00")
        # {name} in quotes like "name" -> match any quoted string
        # {param} not in quotes -> match any non-whitespace
        result = self._replace_params(result)
        result = result.replace("\x00BRACE\x00", r"\{")
        result = re.sub(r'\s+', r'\\s*', result)
        # We've already handled { and }, now escape other specials
        # But be careful not to double-escape
        special_chars = r'[\.\+\*\?\^\$\[\]\|]'
        result = result.strip()

        return result

    def _replace_params(self, header: str) -> str:
        """
        Replace parameter placeholders with appropriate regex wildcards.

        Rules:
        - {param} inside quotes like "{param}" -> "[^"]*"
        - {param} outside quotes -> \S+ (non-whitespace)

        Args:
            header: Template header with possible {param} placeholders
        """
        result = []
        i = 0
        in_quote = False
        quote_char = None

        while i < len(header):
            char = header[i]

            # Track quote state
            if char in '"\'':
                if not in_quote:
                    in_quote = True
                    quote_char = char
                    result.append(char)
                elif char == quote_char:
                    in_quote = False
                    quote_char = None
                    result.append(char)
                else:
                    result.append(char)
                i += 1
                continue

            # Check for parameter placeholder
            if char == '{' and i + 1 < len(header) and header[i + 1] != '{':
                # Find closing }
                end = header.find('}', i)
                if end != -1:
                    # Extract param name
                    param_name = header[i + 1:end]
                    if param_name in self.params or param_name not in ('content',):
                        # Replace with appropriate wildcard
                        if in_quote:
                            # Inside quotes: match any characters except the quote
                            result.append('[^' + quote_char + ']*')
                        else:
                            # Outside quotes: match non-whitespace
                            result.append(r'\S+')
                    else:
                        # Unknown param, keep as-is but escaped
                        result.append(r'\{' + param_name + r'\}')
                    i = end + 1
                    continue

            result.append(char)
            i += 1

        return ''.join(result)

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

    Class Attributes:
        conf_suffix: Configuration file suffix for this DNS software (default: ".conf")
        include_tpl: Include statement template (e.g., 'include "{path}";')

    Example:

        class UnboundSection(Section):
            conf_suffix = ".conf"  # Unbound uses .conf files

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

        class KnotResolverSection(Section):
            conf_suffix = ".conf"

            @classmethod
            def get_sections(cls) -> Dict[str, SectionInfo]:
                return {
                    "global": SectionInfo(name="global"),
                }
    """

    # Cache for section info
    _sections_cache: ClassVar[Optional[Dict[str, SectionInfo]]] = None

    # Configuration file suffix - subclasses can override
    conf_suffix: ClassVar[str] = constants.DEFAULT_CONF_SUFFIX

    # Include statement template - subclasses can override
    include_tpl: ClassVar[str] = ""

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

        Examples:
            for DNS software Unbound, `server` block can appear multiple times, thus Section.server is repeatable.

            for DNS software BIND, `options` block can NOT appear multiple times, thus Section.options is NOT repeatable.
            
            for DNS software BIND, `zone` block can appear multiple times, thus Section.zone is repeatable.

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
        cls, section: str, base_name: Optional[str] = None
    ) -> str:
        """
        Generate filename for a specific section.

        Uses the class's conf_suffix to construct the filename.

        Args:
            section: Section name
            base_name: Base filename without suffix (default: GENERATED_ZONES_BASENAME)

        Returns:
            Filename with appropriate suffix
        """
        if base_name is None:
            base_name = constants.GENERATED_ZONES_BASENAME

        section_info = cls.get_section(section)
        suffix = cls.conf_suffix

        if section_info:
            # Append suffix to the base filename from section_info
            filename = section_info.get_filename(base_name)
            # Only add suffix if not already present
            if not filename.endswith(suffix):
                filename = f"{filename}{suffix}" if "." not in filename else filename
            return filename

        # Fallback for unknown sections
        if section == "global":
            return f"{base_name}{suffix}"

        sinfo = cls.get_section(section)
        if not sinfo or not sinfo.params:
            return f"{base_name}{suffix}.{section}"
        else:
            return f"{base_name}{suffix}?{"&".join(f"{k}={v}" for k, v in sinfo.params.items())}#{section}"

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