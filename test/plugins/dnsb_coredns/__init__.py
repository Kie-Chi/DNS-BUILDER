"""
CoreDNS Plugin for DNS Builder

This plugin adds support for CoreDNS server to DNS Builder.

Usage:
    # Via entry points (in pyproject.toml):
    [project.entry-points."dnsb.plugins"]
    coredns = "dnsb_coredns:CoreDNSPlugin"

    # Or via config.yml:
    plugins:
      - "test.plugins.dnsb_coredns:CoreDNSPlugin"

    # Or via environment variable:
    export DNSB_PLUGINS="test.plugins.dnsb_coredns:CoreDNSPlugin"
"""

import logging
from typing import Dict, Any, Optional, List

# Import from dnsbuilder
from dnsbuilder.plugins import Plugin, PluginRegistry
from dnsbuilder.abstractions import InternalImage, Behavior, MasterBehavior, Includer
from dnsbuilder.datacls import BehaviorArtifact, VolumeArtifact, Pair
from dnsbuilder.datacls.contexts import BuildContext

logger = logging.getLogger(__name__)


# =============================================================================
# CoreDNS Includer Implementation
# =============================================================================

class CoreDNSIncluder(Includer):
    """
    CoreDNS Includer implementation.

    CoreDNS uses a single Corefile for all configuration, without traditional
    include mechanism. This Includer directly appends generated config content
    to the main Corefile.
    """

    def include(self, pair: Pair):
        """
        Append generated config content to the main Corefile.

        Unlike BIND which uses `include "file";`, CoreDNS directly embeds
        the configuration content into the main Corefile.

        Args:
            pair: Pair containing src (host path) and dst (container path)

        Returns:
            None (the content is directly appended)
        """
        block = self.parse_blk(pair)
        if block is None:
            block = "global"

        # Get the main config file (Corefile)
        conf = self.confs.get(block, None)
        if conf is None:
            logger.warning(
                f"[CoreDNSIncluder] No main config found for block '{block}', "
                f"cannot include '{pair.dst}'"
            )
            return None

        # Read the generated config content
        try:
            generated_content = self.fs.read_text(pair.src)
        except Exception as e:
            logger.error(
                f"[CoreDNSIncluder] Failed to read generated config '{pair.src}': {e}"
            )
            return None

        # Append to main Corefile with a comment header
        append_content = f"\n# Auto-included from {pair.dst}\n{generated_content}\n"
        self.fs.append_text(conf.src, append_content)

        logger.debug(
            f"[CoreDNSIncluder] Appended config from '{pair.src}' to main Corefile"
        )

        # Return None means the original volume mount is not modified
        return None

    def contain(self):
        """
        No additional containment needed for CoreDNS.

        All configuration is already in the main Corefile.
        """
        pass


# =============================================================================
# CoreDNS Image Implementation
# =============================================================================

class CoreDNSImage(InternalImage):
    """
    CoreDNS Docker Image implementation.

    CoreDNS is a DNS server that chains plugins and provides DNS services.
    It's written in Go and uses a Corefile for configuration.
    """

    def _post_init_hook(self):
        """CoreDNS-specific initialization."""
        # CoreDNS uses a single binary, minimal dependencies
        # Set the base OS if not already set
        if not hasattr(self, 'os') or self.os == 'ubuntu':
            self.os = "debian"
        logger.debug(f"[CoreDNSImage] Initialized for {self.name}")


# =============================================================================
# CoreDNS Behavior Implementations
# =============================================================================

class CoreDNSForwardBehavior(Behavior):
    """
    CoreDNS forward behavior implementation.

    Generates Corefile forward configuration for proxying DNS requests.
    """

    def generate(
        self,
        service_name: str,
        build_context: BuildContext
    ) -> BehaviorArtifact:
        """
        Generate CoreDNS forward configuration.

        Args:
            service_name: The name of the service
            build_context: Build context with service IPs

        Returns:
            BehaviorArtifact with Corefile configuration
        """
        # Resolve target IPs
        target_ips = MasterBehavior.resolve_ips(
            self.targets, build_context, service_name
        )

        # CoreDNS Corefile format for forward
        # Example:
        # example.com:53 {
        #     forward . 8.8.8.8 8.8.4.4
        # }
        forward_targets = " ".join(target_ips)

        if self.zone == ".":
            # Forward all queries
            config_line = f""".:53 {{
    forward . {forward_targets}
    log
    errors
}}"""
        else:
            # Forward specific zone
            config_line = f"""{self.zone}:53 {{
    forward . {forward_targets}
    log
    errors
}}"""

        return BehaviorArtifact(config_line=config_line)


class CoreDNSStubBehavior(Behavior):
    """
    CoreDNS stub behavior implementation.

    Uses the forward plugin for stub-like behavior in CoreDNS.
    """

    def generate(
        self,
        service_name: str,
        build_context: BuildContext
    ) -> BehaviorArtifact:
        """Generate stub-like configuration using forward."""
        target_ips = MasterBehavior.resolve_ips(
            self.targets, build_context, service_name
        )

        forward_targets = " ".join(target_ips)
        config_line = f"""{self.zone}:53 {{
    forward . {forward_targets}
    log
    errors
}}"""

        return BehaviorArtifact(config_line=config_line)


class CoreDNSHintBehavior(Behavior):
    """
    CoreDNS hint (root hints) behavior implementation.

    Configures root hints for the DNS server.
    """

    LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

    def generate(
        self,
        service_name: str,
        build_context: BuildContext
    ) -> BehaviorArtifact:
        """Generate root hints configuration."""
        target_ips = MasterBehavior.resolve_ips(
            self.targets, build_context, service_name
        )

        # Generate hint entries
        hint_entries = []
        for idx, (target_name, target_ip) in enumerate(
            zip(self.targets, target_ips)
        ):
            import ipaddress
            try:
                ipaddress.ip_address(target_name)
                letter = self.LETTERS[idx % len(self.LETTERS)]
                ns_name = f"{letter}.ROOT-SERVERS.NET."
            except ValueError:
                ns_name = f"{target_name}.servers.net."

            hint_entries.append(f"{ns_name} {target_ip}")

        hints_content = "\n".join(hint_entries)

        # CoreDNS uses the root plugin for hints
        filename = f"root.hints"
        container_path = f"/etc/coredns/{filename}"

        config_line = f""".:53 {{
    root {container_path}
    forward . {" ".join(target_ips)}
    log
    errors
}}"""

        volume = VolumeArtifact(
            filename=filename,
            content=hints_content,
            container_path=container_path
        )

        return BehaviorArtifact(
            config_line=config_line,
            new_volume=volume
        )


class CoreDNSMasterBehavior(MasterBehavior):
    """
    CoreDNS master (authoritative) behavior implementation.

    Serves authoritative zones using the file plugin.
    """

    def generate_config_line(self, zone_name: str, file_path: str) -> str:
        """Generate CoreDNS file plugin configuration."""
        return f"""{zone_name}:53 {{
    file {file_path}
    log
    errors
}}"""


# =============================================================================
# CoreDNS Plugin Definition
# =============================================================================

class CoreDNSPlugin(Plugin):
    """
    CoreDNS Plugin for DNS Builder.

    This plugin enables DNS Builder to generate CoreDNS configurations
    and Docker images.
    """

    # Plugin metadata
    name = "coredns"
    version = "1.0.0"
    description = "CoreDNS server support for DNS Builder"
    author = "DNS Builder Team"
    priority = 50  # Higher priority (lower number = earlier load)

    def on_load(self, registry: PluginRegistry):
        """
        Register CoreDNS implementations.

        Args:
            registry: The plugin registry to register with
        """
        logger.info("[CoreDNSPlugin] Loading CoreDNS plugin...")

        # Register Image
        registry.register_image("coredns", CoreDNSImage)

        # Register Behaviors
        registry.register_behavior(
            "coredns", "forward", CoreDNSForwardBehavior
        )
        registry.register_behavior(
            "coredns", "stub", CoreDNSStubBehavior
        )
        registry.register_behavior(
            "coredns", "hint", CoreDNSHintBehavior
        )
        registry.register_behavior(
            "coredns", "master", CoreDNSMasterBehavior
        )

        # Register Includer
        registry.register_includer("coredns", CoreDNSIncluder)

        # Register Resources (templates, defaults, controls)
        registry.register_resources(
            "coredns",
            "dnsb_coredns.resources",
            templates=True,
            defaults=False,  # CoreDNS doesn't need defaults
            controls=True,
            scripts=False
        )

        # Register Build Templates (for ref: std:auth, std:forwarder, etc.)
        registry.register_build_template("coredns", "auth", {
            "command": "coredns -conf /etc/coredns/Corefile",
            "volumes": [
                "${origin}./${name}/contents:/etc/coredns:rw"
            ]
        })
        registry.register_build_template("coredns", "forwarder", {
            "command": "coredns -conf /etc/coredns/Corefile",
            "volumes": [
                "${origin}./${name}/contents:/etc/coredns:rw"
            ]
        })
        registry.register_build_template("coredns", "recursor", {
            "command": "coredns -conf /etc/coredns/Corefile",
            "volumes": [
                "${origin}./${name}/contents:/etc/coredns:rw"
            ]
        })

        logger.info(
            "[CoreDNSPlugin] Registered: image=coredns, "
            "behaviors=[forward, stub, hint, master], "
            "includer=enabled, resources=enabled, build_templates=[auth, forwarder, recursor]"
        )

    def on_unload(self):
        """Cleanup when plugin is unloaded."""
        logger.info("[CoreDNSPlugin] Unloading CoreDNS plugin...")


# Export for entry points
__all__ = ['CoreDNSPlugin']