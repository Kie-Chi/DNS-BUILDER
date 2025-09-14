import shutil
import logging
from typing import Dict, Any, List, Tuple
import collections

from ..bases.internal import InternalImage
from ..bases.external import LocalImage
from ..datacls.contexts import BuildContext
from ..datacls.artifacts import BehaviorArtifact
from ..datacls.volume import Volume
from ..bases.behaviors import MasterBehavior
from .zone import ZoneGenerator
from .. import constants
from ..utils.path import DNSBPath
from ..exceptions import BuildError, VolumeError, BehaviorError


logger = logging.getLogger(__name__)

class ServiceHandler:
    """
    Handles all artifact generation for a single service.
    """
    def __init__(self, service_name: str, context: BuildContext):
        self.service_name = service_name
        self.context = context
        self.build_conf = context.resolved_builds[service_name]

        self.image_name = self.build_conf.get('image', "")
        self.image_obj = context.images.get(self.image_name)
        self.is_internal_image = isinstance(self.image_obj, InternalImage)
        self.has_dockerfile = self.is_internal_image or isinstance(self.image_obj, LocalImage)

        self.ip = context.service_ips.get(service_name)
        
        self.service_dir = self.context.output_dir / self.service_name
        self.contents_dir = self.service_dir / 'contents'
        self.processed_volumes: List[str] = []
        ip_display = f"with IP '{self.ip}'" if self.ip else "with dynamic IP"
        logger.debug(f"ServiceHandler initialized for '{self.service_name}' {ip_display} and image '{self.image_name}'.")

    def generate_all(self) -> Dict[str, Any]:
        """Orchestrates artifact generation and returns the docker-compose service block."""
        logger.info(f"Generating artifacts for service: '{self.service_name}'...")
        self._setup_service_directory()
        self.image_obj.write(directory=self.service_dir)
        
        main_conf_path = self._process_volumes()
        self._process_behavior(main_conf_path)
        
        compose_service_block = self._assemble_compose_service()
        logger.debug(f"Generated docker-compose block for '{self.service_name}': {compose_service_block}")
        return compose_service_block

    def _setup_service_directory(self):
        self.contents_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created service directory for '{self.service_name}' at '{self.service_dir}'")

    def _process_volumes(self) -> DNSBPath | None:
        main_conf_output_path: DNSBPath | None = None
        for volume_str in self.build_conf.get('volumes', []):
            logger.debug(f"Processing volume string for '{self.service_name}': '{volume_str}'")
            try:
                volume = Volume(volume_str)
            except BuildError as e:
                raise VolumeError(f"Invalid volume format in service '{self.service_name}': {e}")

            host_path = volume.src
            container_path = volume.dst.origin

            if not host_path.is_resource:
                if not host_path.exists():
                    if not host_path.is_absolute():
                        raise VolumeError(f"Volume relative source path does not exist: '{host_path.origin}'")
                    else:
                        logger.warning(f"Volume absolute source path does not exist: '{host_path.origin}', please check if it is in WSL etc.")

            if not host_path.is_resource and host_path.is_absolute():
                # absolute path (except resource) we mount, but not copy
                final_volume_str = volume_str
                logger.debug(f"Absolute path '{host_path.origin}' detected. It will be mounted directly.")
                self.processed_volumes.append(final_volume_str)
            else:
                # relative path or resource path, copy to contents directory
                filename = host_path.name
                target_path = self.contents_dir / filename
                shutil.copy(host_path, target_path)
                if container_path.endswith('.conf'):
                    if not main_conf_output_path:
                        main_conf_output_path = target_path
                        logger.debug(f"Identified '{filename}' as the main configuration file.")
                    else:
                        logger.debug(f"Found additional config file '{filename}', will attempt to include it in the main config.")
                        if main_conf_output_path.read_text().find(container_path) != -1:
                            logger.debug(f"Include line for '{container_path}' already exists, skipping auto-include.")
                        else:
                            self.context.includer_factory.create(container_path, self.image_obj.software).write(str(main_conf_output_path))
                
                final_volume_str = f"./{self.service_name}/contents/{filename}:{container_path}"
                if volume.mode:
                    final_volume_str += f":{volume.mode}"
                self.processed_volumes.append(final_volume_str)
                logger.debug(f"Relative/resource path copied and added as processed volume: {final_volume_str}")
        return main_conf_output_path

    def _generate_artifacts_from_behaviors(
        self,
    ) -> Tuple[List[BehaviorArtifact], List[Tuple[BehaviorArtifact, MasterBehavior]]]:
        """Parses all behavior lines and generates initial artifacts."""
        standard_artifacts = []
        master_artifacts_with_obj = []
        behavior_str = self.build_conf.get("behavior", "")

        for line in behavior_str.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            logger.debug(f"Parsing behavior line: '{line}'")
            behavior_obj = self.context.behavior_factory.create(
                line, self.image_obj.software
            )
            artifact = behavior_obj.generate(self.service_name, self.context)

            if isinstance(behavior_obj, MasterBehavior):
                master_artifacts_with_obj.append((artifact, behavior_obj))
            else:
                standard_artifacts.append(artifact)

        return standard_artifacts, master_artifacts_with_obj

    def _process_master_zones(
        self, master_artifacts_with_obj: List[Tuple[BehaviorArtifact, MasterBehavior]]
    ) -> Dict[constants.BehaviorSection, List[str]]:
        """Aggregates master records, generates zone files, and creates config lines."""
        all_config_lines = collections.defaultdict(list)
        if not master_artifacts_with_obj:
            return all_config_lines

        records_by_zone = collections.defaultdict(list)
        behavior_by_zone = {}

        # 1. Aggregate records by the zone file key specified in the behavior
        for artifact, behavior_obj in master_artifacts_with_obj:
            zone_key = behavior_obj.zone_file_key
            for record in artifact.new_records:
                records_by_zone[zone_key].append(record)

            if zone_key not in behavior_by_zone:
                behavior_by_zone[zone_key] = behavior_obj

        gen_vol_dir = self.contents_dir / constants.GENERATED_ZONES_SUBDIR
        gen_vol_dir.mkdir(exist_ok=True)

        # 2. Generate zone file and config line for each aggregated zone
        for zone, records in records_by_zone.items():
            generator = ZoneGenerator(self.context, zone, self.service_name, records)
            zone_content = generator.generate_zone_file()

            filename = f"db.{zone}" if zone != "." else "db.root"
            filepath = gen_vol_dir / filename
            filepath.write_text(zone_content)

            container_path = f"/usr/local/etc/zones/{filename}"
            volume_str = f"./{self.service_name}/contents/{constants.GENERATED_ZONES_SUBDIR}/{filename}:{container_path}"
            self.processed_volumes.append(volume_str)
            logger.debug(f"Generated master zone file and volume: {volume_str}")

            behavior_obj = behavior_by_zone[zone]
            config_line = behavior_obj.generate_config_line(zone, container_path)
            all_config_lines[constants.BehaviorSection.TOPLEVEL].append(config_line)

        return all_config_lines

    def _process_behavior(self, main_conf_path: DNSBPath | None):
        """Orchestrates the entire behavior processing workflow."""
        if not self.build_conf.get("behavior"):
            logger.debug(f"Service '{self.service_name}' has no behavior to process.")
            return

        logger.debug(f"Processing behavior for '{self.service_name}'...")
        if not main_conf_path:
            raise BehaviorError(
                f"Service '{self.service_name}' has 'behavior' but no main .conf file."
            )
        if not self.is_internal_image or not self.image_obj.software:
            raise BehaviorError(
                f"Cannot process 'behavior' for '{self.service_name}': image '{self.image_obj.name}' must be internal and have a 'software' type."
            )

        # Step 1: Generate all artifacts from behavior lines
        standard_artifacts, master_artifacts_with_obj = (
            self._generate_artifacts_from_behaviors()
        )

        # Step 2: Process master zone artifacts to generate zone files and their config lines
        all_config_lines = self._process_master_zones(master_artifacts_with_obj)

        # Step 3: Process standard (non-master) artifacts
        for artifact in standard_artifacts:
            logger.debug(
                f"Generated behavior artifact: section='{artifact.section}', line='{artifact.config_line.replace(chr(10), ' ')}'"
            )
            all_config_lines[artifact.section].append(artifact.config_line)

            if artifact.new_volume:
                vol = artifact.new_volume
                gen_vol_dir = self.contents_dir / constants.GENERATED_ZONES_SUBDIR
                gen_vol_dir.mkdir(exist_ok=True)
                filepath = gen_vol_dir / vol.filename
                filepath.write_text(vol.content)
                final_volume_str = f"./{self.service_name}/contents/{constants.GENERATED_ZONES_SUBDIR}/{vol.filename}:{vol.container_path}"
                self.processed_volumes.append(final_volume_str)
                logger.debug(
                    f"Generated and added new volume from behavior: {final_volume_str}"
                )

        # Step 4: Write all collected config lines to the generated zones file
        generated_zones_content = self._format_behavior_config(all_config_lines)
        if not generated_zones_content.strip():
            return

        gen_zones_path = self.contents_dir / constants.GENERATED_ZONES_FILENAME
        gen_zones_path.write_text(
            f"# Auto-generated by DNS Builder\n\n{generated_zones_content}\n"
        )
        logger.debug(f"Wrote generated behavior config to '{gen_zones_path}'.")

        container_conf_path = (
            f"/usr/local/etc/zones/{constants.GENERATED_ZONES_FILENAME}"
        )
        self.processed_volumes.append(
            f"./{self.service_name}/contents/{constants.GENERATED_ZONES_FILENAME}:{container_conf_path}"
        )

        includer = self.context.includer_factory.create(
            container_conf_path, self.image_obj.software
        )
        includer.write(str(main_conf_path))
        logger.debug(
            f"Appended include directive for '{container_conf_path}' to '{main_conf_path}'."
        )

    def _format_behavior_config(
        self, config_lines_by_section: Dict[constants.BehaviorSection, List[str]]
    ) -> str:
        """Formats the collected behavior config lines"""
        output_parts = []
        software_type = self.image_obj.software

        if software_type == "unbound":
            server_lines = config_lines_by_section.get(
                constants.BehaviorSection.SERVER, []
            )
            if server_lines:
                output_parts.append("server:")
                for line in server_lines:
                    indented_line = "\n".join(
                        [f"    {sub_line}" for sub_line in line.split("\n")]
                    )
                    output_parts.append(indented_line)

        # For both 'bind' and 'unbound', toplevel lines are added at the root.
        toplevel_lines = config_lines_by_section.get(
            constants.BehaviorSection.TOPLEVEL, []
        )
        output_parts.extend(toplevel_lines)

        return "\n\n".join(output_parts)

    def _assemble_compose_service(self) -> Dict:
        logger.debug(f"Assembling final docker-compose service block for '{self.service_name}'.")
        service_config = {
            'container_name': f"{self.context.config.name}-{self.service_name}",
            'hostname': self.service_name
        }
        if self.has_dockerfile:
            service_config['build'] = f"./{self.service_name}"
        else:
            if not self.image_name:
                 raise BuildError(f"Service '{self.service_name}' is configured for a Non-Dockerfile build, but the 'image' key is missing.")
            service_config['image'] = self.image_name
        if self.ip:
            service_config['networks'] = {
                constants.DEFAULT_NETWORK_NAME: {'ipv4_address': self.ip}
            }
        else:
            # with no `networks`
            pass
        passthrough_mounts = self.build_conf.get('mounts', [])
        final_volumes = self.processed_volumes + passthrough_mounts
        if final_volumes: 
            service_config['volumes'] = sorted(list(set(final_volumes)))
        if 'mounts' in self.build_conf: 
            del self.build_conf['mounts']
        
        if 'cap_add' in self.build_conf:
            service_config['cap_add'] = self.build_conf['cap_add']
        else:
            service_config['cap_add'] = constants.DEFAULT_CAP_ADD
        for key, value in self.build_conf.items():
            if key not in constants.RESERVED_BUILD_KEYS: 
                service_config[key] = value
        return service_config
    
