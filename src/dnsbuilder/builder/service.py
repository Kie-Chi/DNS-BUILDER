import logging
from typing import Dict, Any, List, Tuple
import collections
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

from ..bases.internal import InternalImage
from ..bases.external import SelfDefinedImage
from ..datacls.contexts import BuildContext
from ..datacls.artifacts import BehaviorArtifact
from ..datacls.volume import Volume
from ..bases.behaviors import MasterBehavior
from .zone import ZoneGenerator
from .. import constants
from ..io.path import DNSBPath
from ..io.fs import FileSystem, create_app_fs
from ..exceptions import BuildError, VolumeError, BehaviorError, BuildDefinitionError

logger = logging.getLogger(__name__)


@dataclass
class ConfigGenerationTrace:
    """Trace configuration generation process for debugging and analysis"""
    service_name: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    stages: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    fs: FileSystem = field(default_factory=create_app_fs)
    
    def add_stage(self, stage_name: str, description: str, details: Dict[str, Any] = None):
        """Add processing stage record"""
        stage_info = {
            "stage": stage_name,
            "description": description,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        }
        self.stages.append(stage_info)
        logger.debug(f"[TRACE] {self.service_name} - {stage_name}: {description}")
    
    def add_decision(self, decision_type: str, description: str, source: str, value: Any, reason: str = ""):
        """Add automatic decision record"""
        decision_info = {
            "type": decision_type,
            "description": description,
            "source": source,
            "value": value,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        self.decisions.append(decision_info)
        logger.debug(f"[TRACE] {self.service_name} - Decision: {description} = {value} (from {source})")
    
    def add_warning(self, message: str):
        """Add warning message"""
        self.warnings.append(f"{datetime.now().isoformat()}: {message}")
        logger.warning(f"[TRACE] {self.service_name} - Warning: {message}")
    
    def add_error(self, message: str):
        """Add error message"""
        self.errors.append(f"{datetime.now().isoformat()}: {message}")
        logger.error(f"[TRACE] {self.service_name} - Error: {message}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            "service_name": self.service_name,
            "timestamp": self.timestamp,
            "stages": self.stages,
            "decisions": self.decisions,
            "warnings": self.warnings,
            "errors": self.errors
        }
    
    def save_report(self, output_path: DNSBPath):
        """Save trace report to file using the file system abstraction"""
        report_data = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        self.fs.write_text(output_path, report_data)


class ServiceHandler:
    """
    Handles all artifact generation for a single service.
    """
    def __init__(self, service_name: str, context: BuildContext):
        self.service_name = service_name
        self.context = context
        self.build_conf = context.resolved_builds[service_name]
        
        # Initialize configuration generation tracer
        self.trace = ConfigGenerationTrace(service_name, fs=context.fs)
        self.trace.add_stage("initialization", "ServiceHandler initialization started")

        self.image_name = self.build_conf.get('image', "")
        self.image_obj = context.images.get(self.image_name)
        self.is_internal_image = isinstance(self.image_obj, InternalImage)
        self.has_dockerfile = self.is_internal_image or isinstance(self.image_obj, SelfDefinedImage)

        # Record image-related decisions
        self.trace.add_decision(
            "image_selection", 
            "Service image selection", 
            "build_conf", 
            self.image_name,
            "Retrieved image name from build configuration"
        )
        
        if self.is_internal_image:
            self.trace.add_decision(
                "image_type", 
                "Image type determination", 
                "image_obj", 
                "internal",
                "Image is internal, will use build method"
            )
        elif isinstance(self.image_obj, SelfDefinedImage):
            self.trace.add_decision(
                "image_type", 
                "Image type determination", 
                "image_obj", 
                "self_defined",
                "Image is self-defined, will use build method"
            )
        else:
            self.trace.add_decision(
                "image_type", 
                "Image type determination", 
                "image_obj", 
                "docker",
                "Image is docker, will use image method"
            )

        self.ip = context.service_ips.get(service_name)
        
        # Record IP allocation decisions
        if self.ip:
            self.trace.add_decision(
                "ip_allocation", 
                "IP address allocation", 
                "service_ips", 
                self.ip,
                "Retrieved static IP from service IP configuration"
            )
        else:
            self.trace.add_decision(
                "ip_allocation", 
                "IP address allocation", 
                "default", 
                "dynamic",
                "No static IP configured, will use dynamic IP allocation"
            )
        
        self.service_dir = self.context.output_dir / self.service_name
        self.contents_dir = self.service_dir / 'contents'
        self.processed_volumes: List[str] = []
        
        ip_display = f"with IP '{self.ip}'" if self.ip else "with dynamic IP"
        logger.debug(f"ServiceHandler initialized for '{self.service_name}' {ip_display} and image '{self.image_name}'.")
        
        self.trace.add_stage("initialization", "ServiceHandler initialization completed", {
            "service_name": self.service_name,
            "image_name": self.image_name,
            "ip": self.ip,
            "has_dockerfile": self.has_dockerfile
        })

    def generate_all(self) -> Dict[str, Any]:
        """Orchestrates artifact generation and returns the docker-compose service block."""
        self.trace.add_stage("generation_start", "Start generating all artifacts")
        logger.info(f"Generating artifacts for service: '{self.service_name}'...")
        
        # Setup service directory
        self.trace.add_stage("setup_directory", "Setup service directory")
        self._setup_service_directory()
        
        # Write image files
        self.trace.add_stage("write_image", "Write image related files")
        self.image_obj.write(directory=self.service_dir)
        
        # Process files
        self.trace.add_stage("process_files", "Process service files")
        self._process_files()

        # Process extra_conf
        self.trace.add_stage("process_extra_conf", "Process extra_conf configuration")
        self._process_extra_conf()
        
        # Process volume mounts
        self.trace.add_stage("process_volumes", "Process volume mount configuration")
        main_conf_path = self._process_volumes()
        if main_conf_path:
            self.trace.add_decision(
                "main_config_path", 
                "Main configuration file path", 
                "_process_volumes", 
                str(main_conf_path),
                "Obtained main config file path from volume processing"
            )
        
        # Process behavior configuration
        self.trace.add_stage("process_behavior", "Process behavior configuration")
        self._process_behavior(main_conf_path)
        
        # Assemble compose service block
        self.trace.add_stage("assemble_compose", "Assemble docker-compose service configuration")
        compose_service_block = self._assemble_compose_service()
        
        # Validate required fields
        self.trace.add_stage("validate_fields", "Validate required fields")
        self._validate_required_fields()
        
        self.trace.add_stage("generation_complete", "Artifact generation completed", {
            "compose_service_keys": list(compose_service_block.keys()),
            "total_stages": len(self.trace.stages),
            "total_decisions": len(self.trace.decisions)
        })
        
        logger.debug(f"Generated docker-compose block for '{self.service_name}': {compose_service_block}")
        if logger.isEnabledFor(logging.DEBUG):
            rep_path = self.save_generation_report()
            logger.debug(f"[{self.service_name}] Generation report saved to '{rep_path}'.")
        return compose_service_block
    
    def _validate_required_fields(self):
        """
        Recursively checks the service configuration for any unfulfilled '${required}' placeholders.
        """
        logger.debug(f"[{self.service_name}] Validating required fields...")
        errors = []

        def check_item(item, path_prefix=""):
            if isinstance(item, dict):
                for key, value in item.items():
                    new_path = f"{path_prefix}.{key}" if path_prefix else key
                    check_item(value, new_path)
            elif isinstance(item, str) and item == constants.PLACEHOLDER['REQUIRED']:
                errors.append(path_prefix)

        check_item(self.build_conf)

        if errors:
            error_messages = ", ".join([f"'{e}'" for e in errors])
            raise BuildDefinitionError(
                f"Service '{self.service_name}' is missing required configuration values for the following keys: {error_messages}. "
                "Please provide a value for these keys in your config file."
            )
        logger.debug(f"[{self.service_name}] All required fields are present.")

    def _setup_service_directory(self):
        self.context.fs.mkdir(self.contents_dir, parents=True, exist_ok=True)
        logger.debug(f"Created service directory for '{self.service_name}' at '{self.service_dir}'")

    def __filter_volumes(self) -> List[Volume]:
        origin_volumes = self.build_conf.get('volumes', [])
        filtered_volumes = []
        required_volumes = []
        for volume_str in origin_volumes:
            try:
                volume = Volume(volume_str)
            except (BuildError, VolumeError) as e:
                raise VolumeError(f"Invalid volume format in service '{self.service_name}': {e}")
            if volume.is_required:
                required_volumes.append(volume)
            else:
                filtered_volumes.append(volume)

        def is_implemented(volume: Volume) -> bool:
            for filterd in filtered_volumes:
                if volume.dst == filterd.dst:
                    return True
            return False
        
        not_satisfied = [required for required in required_volumes if not is_implemented(required)]
        if not_satisfied:
            raise VolumeError(f"Required volumes mount to {[str(v.dst) for v in not_satisfied]}, but not implemented.")
                    
        return filtered_volumes

    def _process_files(self):
        files = self.build_conf.get('files', {})
        if not files:
            return
        
        logger.debug(f"Generating temporary volumes for '{self.service_name}'...")
        for container_path, content in files.items():            
            extension = DNSBPath(container_path).suffix
            # Generate semantic hash based on service name, container path and content
            content_hash = hashlib.sha256(f"{self.service_name}:{container_path}:{content}".encode()).hexdigest()[:24]
            temp_uri = DNSBPath(f"temp:/{content_hash}{extension}")
            
            # Handle collision (very unlikely with SHA256)
            counter = 0
            while self.context.fs.exists(temp_uri):
                counter += 1
                collision_hash = hashlib.sha256(f"{self.service_name}:{container_path}:{content}:{counter}".encode()).hexdigest()[:24]
                temp_uri = DNSBPath(f"temp:/{collision_hash}{extension}")

            self.context.fs.write_text(temp_uri, content)
            volume_str = f"{str(temp_uri)}:{container_path}"
            self.build_conf.setdefault('volumes', []).append(volume_str)
            logger.debug(f"Generated temporary volume: {volume_str}")

    def _process_extra_conf(self):
        """Process extra_conf field"""
        extra_conf = self.build_conf.get('extra_conf')
        if not extra_conf:
            return
        logger.debug(f"Processing extra_conf for '{self.service_name}'...")
        
        content_hash = hashlib.sha256(f"{self.service_name}:extra_conf:{extra_conf}".encode()).hexdigest()[:24]
        temp_uri = DNSBPath(f"temp:/{content_hash}.conf")
        counter = 0
        while self.context.fs.exists(temp_uri):
            counter += 1
            collision_hash = hashlib.sha256(f"{self.service_name}:extra_conf:{extra_conf}:{counter}".encode()).hexdigest()[:24]
            temp_uri = DNSBPath(f"temp:/{collision_hash}.conf")
        self.context.fs.write_text(temp_uri, extra_conf)
        container_path = f"/usr/local/etc/extra_{self.service_name}.conf"
        volume_str = f"{str(temp_uri)}:{container_path}"
        self.build_conf.setdefault('volumes', []).append(volume_str)
        logger.debug(f"Generated extra_conf volume: {volume_str}")

    def _process_volumes(self) -> DNSBPath | None:
        main_conf_output_path: DNSBPath | None = None
        filtered_volumes = self.__filter_volumes()
        for volume in filtered_volumes:
            logger.debug(f"Processing volume for '{self.service_name}': '{volume}'")
            host_path = volume.src
            container_path = volume.dst
            if host_path.need_check:
                if not self.context.fs.exists(host_path):
                    if not host_path.is_absolute():
                        raise VolumeError(f"Volume relative source path does not exist: '{host_path}'")
                    else:
                        logger.warning(f"Volume absolute source path does not exist: '{host_path}', please check if it is in WSL etc.")

            if not host_path.need_copy:
                # we mount, but not copy
                final_volume_str = str(volume)
                logger.debug(f"Path '{host_path}' detected. It will be mounted directly.")
                self.processed_volumes.append(final_volume_str)
            else:
                # relative path or resource path, copy to contents directory
                filename = None
                target_path = None
                def gen_target_path(filename: DNSBPath) -> DNSBPath:
                    target_path = self.contents_dir / filename
                    if self.context.fs.exists(target_path):
                        target_path = self.contents_dir / f"{hashlib.sha256(str(host_path).encode()).hexdigest()[:16]}-{filename}"
                    return target_path

                if self.context.fs.is_dir(host_path):
                    filename = host_path.__rname__.split(".")[0]
                    target_path = gen_target_path(filename)
                    self.context.fs.copytree(host_path, target_path)
                else:
                    filename = host_path.__rname__
                    target_path = gen_target_path(filename)
                    self.context.fs.copy(host_path, target_path)
                if str(container_path).endswith('.conf'):
                    if not main_conf_output_path:
                        main_conf_output_path = target_path
                        logger.debug(f"Identified '{filename}' as the main configuration file.")
                    else:
                        logger.debug(f"Found additional config file '{filename}', will attempt to include it in the main config.")
                        if self.context.fs.read_text(main_conf_output_path).find(str(container_path)) != -1:
                            logger.debug(f"Include line for '{container_path}' already exists, skipping auto-include.")
                        else:
                            self.context.includer_factory.create(container_path, self.image_obj.software).write(main_conf_output_path)
                
                final_volume_str = f"./{self.service_name}/contents/{filename}:{container_path}"
                if volume.mode:
                    final_volume_str += f":{volume.mode}"
                self.processed_volumes.append(final_volume_str)
                logger.debug(f"Path copied and added as processed volume: {final_volume_str}")
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
        self.context.fs.mkdir(gen_vol_dir, exist_ok=True)

        # 2. Generate zone file and config line for each aggregated zone
        for zone, records in records_by_zone.items():
            generator = ZoneGenerator(self.context, zone, self.service_name, records)
            zone_content = generator.generate_zone_file()

            filename = f"db.{zone}" if zone != "." else "db.root"
            filepath = gen_vol_dir / filename
            self.context.fs.write_text(filepath, zone_content)

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
        if not self.image_obj.software:
            raise BehaviorError(
                f"Cannot process 'behavior' for '{self.service_name}': image '{self.image_obj.name}' must have a 'software' type."
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
                self.context.fs.mkdir(gen_vol_dir, exist_ok=True)
                filepath = gen_vol_dir / vol.filename
                self.context.fs.write_text(filepath, vol.content)
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
        self.context.fs.write_text(
            gen_zones_path, f"# Auto-generated by DNS Builder\n\n{generated_zones_content}\n"
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
        includer.write(main_conf_path)
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

    def _generate_passthrough_config(self, service_config: Dict[str, Any]) -> Dict[str, Any]:
        """Generate passthrough configuration items"""
        passthrough_configs = {}
        for key, value in self.build_conf.items():
            if key not in constants.RESERVED_BUILD_KEYS: 
                service_config[key] = value
                passthrough_configs[key] = value
        
        if passthrough_configs:
            self.trace.add_decision(
                "passthrough_configs", 
                "Passthrough configuration items", 
                "build_conf", 
                passthrough_configs,
                f"Added {len(passthrough_configs)} non-reserved key configuration items"
            )
        
        return passthrough_configs

    def _generate_capability_config(self, service_config: Dict[str, Any]) -> None:
        """Generate container capability configuration"""
        if 'cap_add' in self.build_conf and self.build_conf['cap_add']:
            cap_add_value = self.build_conf['cap_add']
            service_config['cap_add'] = cap_add_value
            self.trace.add_decision(
                "cap_add", 
                "Container capability configuration", 
                "build_conf", 
                cap_add_value,
                "Obtained cap_add setting from build configuration"
            )
        else:
            default_cap_add = constants.DEFAULT_CAP_ADD
            service_config['cap_add'] = default_cap_add
            self.trace.add_decision(
                "cap_add", 
                "Container capability configuration", 
                "default", 
                default_cap_add,
                "Using default cap_add configuration"
            )

    def _generate_volume_config(self, service_config: Dict[str, Any]) -> None:
        """Generate volume mount configuration"""
        passthrough_mounts = self.build_conf.get('mounts', [])
        final_volumes = self.processed_volumes + passthrough_mounts
        
        self.trace.add_decision(
            "volume_processing", 
            "Volume mount processing", 
            "processed_volumes + passthrough_mounts", 
            {
                "processed_volumes_count": len(self.processed_volumes),
                "passthrough_mounts_count": len(passthrough_mounts),
                "total_volumes": len(final_volumes)
            },
            f"Merged processed volumes ({len(self.processed_volumes)}) and passthrough volumes ({len(passthrough_mounts)})"
        )
        
        if final_volumes: 
            # Use set for deduplication and sort
            unique_volumes = sorted(list(set(final_volumes)))
            service_config['volumes'] = unique_volumes
            
            if len(unique_volumes) != len(final_volumes):
                self.trace.add_warning(f"Detected duplicate volume mounts, deduplicated: original {len(final_volumes)}, after deduplication {len(unique_volumes)}")
            
            self.trace.add_decision(
                "final_volumes", 
                "Final volume configuration", 
                "volume_deduplication", 
                unique_volumes,
                "Deduplicated and sorted volume mount list"
            )
        
        # Clean up mounts configuration
        if 'mounts' in self.build_conf: 
            del self.build_conf['mounts']
            self.trace.add_decision(
                "cleanup_mounts", 
                "Clean up mounts configuration", 
                "build_conf", 
                "removed",
                "Removed mounts key from build configuration to avoid duplication"
            )

    def _generate_network_config(self, service_config: Dict[str, Any]) -> None:
        """Generate network configuration"""
        if self.ip:
            network_config = {constants.DEFAULT_NETWORK_NAME: {'ipv4_address': self.ip}}
            service_config['networks'] = network_config
            self.trace.add_decision(
                "network_config", 
                "Network configuration", 
                "static_ip", 
                network_config,
                f"Configured static IP address: {self.ip}"
            )
        else:
            self.trace.add_decision(
                "network_config", 
                "Network configuration", 
                "default", 
                "dynamic",
                "No static IP configured, using default network configuration"
            )

    def _generate_image_build_config(self, service_config: Dict[str, Any]) -> None:
        """Generate image or build configuration"""
        if self.has_dockerfile:
            build_path = f"./{self.service_name}"
            service_config['build'] = build_path
            self.trace.add_decision(
                "build_config", 
                "Build configuration", 
                "has_dockerfile", 
                build_path,
                "Dockerfile detected, using build method"
            )
        else:
            if not self.image_name:
                error_msg = f"Service '{self.service_name}' is configured for a Non-Dockerfile build, but the 'image' key is missing."
                self.trace.add_error(error_msg)
                raise BuildError(error_msg)
            service_config['image'] = self.image_name
            self.trace.add_decision(
                "image_config", 
                "Image configuration", 
                "image_name", 
                self.image_name,
                "No Dockerfile detected, using external image"
            )

    def _generate_basic_config(self) -> Dict[str, str]:
        """Generate basic configuration (container_name, hostname)"""
        container_name = f"{self.context.config.name}-{self.service_name}"
        hostname = self.service_name
        
        self.trace.add_decision(
            "container_name", 
            "Container name", 
            "config_name + service_name", 
            container_name,
            f"Using project name '{self.context.config.name}' and service name '{self.service_name}' combination"
        )
        
        self.trace.add_decision(
            "hostname", 
            "Hostname", 
            "service_name", 
            hostname,
            "Using service name as hostname"
        )
        
        return {
            'container_name': container_name,
            'hostname': hostname
        }

    def _assemble_compose_service(self) -> Dict:
        """Assembles the final docker-compose service block."""
        self.trace.add_stage("assemble_start", "Start assembling docker-compose service configuration")
        logger.debug(f"Assembling final docker-compose service block for '{self.service_name}'.")
        
        # Generate basic configuration
        service_config = self._generate_basic_config()
        
        # Generate image or build configuration
        self._generate_image_build_config(service_config)
        
        # Generate network configuration
        self._generate_network_config(service_config)
        
        # Generate volume mount configuration
        self._generate_volume_config(service_config)
        
        # Generate container capability configuration
        self._generate_capability_config(service_config)
        
        # Generate passthrough configuration
        passthrough_configs = self._generate_passthrough_config(service_config)
        
        self.trace.add_stage("assemble_complete", "Docker-compose service configuration assembly completed", {
            "final_config_keys": list(service_config.keys()),
            "has_build": 'build' in service_config,
            "has_image": 'image' in service_config,
            "has_networks": 'networks' in service_config,
            "has_volumes": 'volumes' in service_config,
            "volume_count": len(service_config.get('volumes', [])),
            "passthrough_count": len(passthrough_configs)
        })
        
        return service_config
    
    def save_generation_report(self, output_dir: DNSBPath = None) -> DNSBPath:
        """Save configuration generation trace report to file"""
        if output_dir is None:
            output_dir = self.service_dir
        
        report_filename = f"{self.service_name}_trace.log"
        report_path = output_dir / report_filename
        
        self.trace.save_report(report_path)
        logger.info(f"Configuration generation trace report saved to: {report_path}")
        return report_path
    
    def get_generation_summary(self) -> Dict[str, Any]:
        """Get summary information of the configuration generation process"""
        return {
            "service_name": self.service_name,
            "total_stages": len(self.trace.stages),
            "total_decisions": len(self.trace.decisions),
            "warnings_count": len(self.trace.warnings),
            "errors_count": len(self.trace.errors),
            "generation_timestamp": self.trace.timestamp,
            "key_decisions": [
                decision for decision in self.trace.decisions 
                if decision["type"] in ["image_selection", "ip_allocation", "network_config", "final_volumes"]
            ]
        }
    
