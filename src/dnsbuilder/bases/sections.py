"""
DNS Builder Section Implementations

This module contains concrete Section implementations for each DNS software.
Each Section class defines the configuration blocks supported by that software,
including template-based formatting rules.

Sections define:
- Supported block names (global, server, options, etc.)
- Template format for each block
- Required parameters for parameterized blocks
- File naming conventions
"""

from typing import Dict, Set
from ..sections import Section, SectionInfo


# ============================================================================
# BIND SECTION
# ============================================================================

class BindSection(Section):
    """
    BIND configuration block definitions.

    BIND uses a hierarchical configuration format with blocks like:
    - options { ... };
    - logging { ... };
    - zone "name" { ... };
    - acl "name" { ... };
    """

    # BIND configuration file suffix
    conf_suffix = ".conf"
    # BIND include statement template
    include_tpl = 'include "{path}";'

    @classmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        return {
            "global": SectionInfo(
                name="global",
                template="{content}",
                indent=0,
            ),
            "options": SectionInfo(
                name="options",
                template="options {{\n{content}\n}};",
                indent=4,
                repeatable=False,  # Only one options block
            ),
            "logging": SectionInfo(
                name="logging",
                template="logging {{\n{content}\n}};",
                indent=4,
                repeatable=False,  # Only one logging block
            ),
            "acl": SectionInfo(
                name="acl",
                template='acl "{name}" {{\n{content}\n}};',
                indent=4,
                params={"name"},
                repeatable=True,  # Multiple ACLs with different names
            ),
            "controls": SectionInfo(
                name="controls",
                template="controls {{\n{content}\n}};",
                indent=4,
                repeatable=False,
            ),
            "key": SectionInfo(
                name="key",
                template='key "{key_name}" {{\n{content}\n}};',
                indent=4,
                params={"key_name"},
                repeatable=True,  # Multiple keys with different names
            ),
            "server": SectionInfo(
                name="server",
                template="server {{\n{content}\n}};",
                indent=4,
                repeatable=False,
            ),
            "trusted-keys": SectionInfo(
                name="trusted-keys",
                template="trusted-keys {{\n{content}\n}};",
                indent=4,
                repeatable=False,
            ),
            "managed-keys": SectionInfo(
                name="managed-keys",
                template="managed-keys {{\n{content}\n}};",
                indent=4,
                repeatable=False,
            ),
            "statistics-channels": SectionInfo(
                name="statistics-channels",
                template="statistics-channels {{\n{content}\n}};",
                indent=4,
                repeatable=False,
            ),
            "zone": SectionInfo(
                name="zone",
                template="zone \"{name}\" {{\n{content}\n}};",
                indent=4,
                params={"name"},
                repeatable=True,  # Multiple zones with different names
            ),
            "view": SectionInfo(
                name="view",
                template="view \"{name}\" {{\n{content}\n}};",
                indent=4,
                params={"name"},
                repeatable=True,  # Multiple views with different names
            ),
        }


# ============================================================================
# UNBOUND SECTION
# ============================================================================

class UnboundSection(Section):
    """
    Unbound configuration block definitions.

    Unbound uses a YAML-like format with blocks like:
    - server:
        - option: value
    - forward-zone:
        - name: "example.com"
        - forward-addr: 1.2.3.4

    Note: Unbound blocks do NOT require closing markers.
    The template uses colon suffix (e.g., "server:") followed by indented content.
    """

    # Unbound configuration file suffix
    conf_suffix = ".conf"
    # Unbound include statement template
    include_tpl = 'include: "{path}"'

    @classmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        return {
            "global": SectionInfo(
                name="global",
                template="{content}",
                indent=0,
            ),
            "server": SectionInfo(
                name="server",
                template="server:\n{content}",
                indent=4,
                repeatable=True,
            ),
            "remote-control": SectionInfo(
                name="remote-control",
                template="remote-control:\n{content}",
                indent=4,
                repeatable=False,
            ),
            "forward-zone": SectionInfo(
                name="forward-zone",
                template="forward-zone:\n{content}",
                indent=4,
                repeatable=True,  # Multiple forward zones allowed
            ),
            "stub-zone": SectionInfo(
                name="stub-zone",
                template="stub-zone:\n{content}",
                indent=4,
                repeatable=True,  # Multiple stub zones allowed
            ),
            "auth-zone": SectionInfo(
                name="auth-zone",
                template="auth-zone:\n{content}",
                indent=4,
                repeatable=True,  # Multiple auth zones allowed
            ),
            "view": SectionInfo(
                name="view",
                template="view:\n{content}",
                indent=4,
                repeatable=True,  # Multiple views allowed
            ),
            "python": SectionInfo(
                name="python",
                template="python:\n{content}",
                indent=4,
                repeatable=False,
            ),
            "dynlib": SectionInfo(
                name="dynlib",
                template="dynlib:\n{content}",
                indent=4,
                repeatable=False,
            ),
        }


# ============================================================================
# POWERDNS RECURSOR SECTION
# ============================================================================

class PdnsRecursorSection(Section):
    """
    PowerDNS Recursor configuration block definitions.

    PowerDNS Recursor uses a simple key=value format without block structure.
    All configuration is in a single "global" section.
    """

    # PowerDNS Recursor configuration file suffix
    conf_suffix = ".conf"
    # PowerDNS Recursor uses include-dir directive, not individual includes
    include_tpl = ""

    @classmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        return {
            "global": SectionInfo(
                name="global",
                template="{content}",
                indent=0,
            ),
        }


# ============================================================================
# KNOT RESOLVER SECTION (< 5.x)
# ============================================================================

class KnotResolverSection(Section):
    """
    Knot Resolver configuration block definitions.

    Knot Resolver uses Lua-based configuration format.
    All configuration is in a single "global" section using Lua syntax.
    """

    # Knot Resolver uses .conf for the main config (which contains Lua)
    conf_suffix = ".conf"
    # Knot Resolver uses dofile() for includes
    include_tpl = "dofile('{path}')"

    @classmethod
    def get_sections(cls) -> Dict[str, SectionInfo]:
        return {
            "global": SectionInfo(
                name="global",
                template="{content}",
                indent=0,
            ),
        }


# ============================================================================
# KNOT RESOLVER 6 SECTION (>= 6.x)
# ============================================================================

class KnotResolver6Section(KnotResolverSection):
    """
    Knot Resolver 6 configuration block definitions.

    Knot Resolver 6 uses the same Lua-based format as earlier versions.
    Inherits from KnotResolverSection.
    """
    pass


# Dynamically generate __all__
from ..utils.reflection import gen_exports

__all__ = gen_exports(
    ns=globals(),
    base_path='dnsbuilder.bases.sections',
    patterns=['Section']
)