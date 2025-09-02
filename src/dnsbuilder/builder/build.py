from pathlib import Path
import shutil
import ipaddress
import yaml
import copy
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from importlib import resources

from .contexts import BuildContext
from .. import constants
from ..config import Config
from .behaviors import BehaviorFactory
from .includers import IncluderFactory
from ..images.factory import ImageFactory
from ..images.image import Image
from ..exceptions import BuildError, VolumeNotFoundError, ConfigError, CircularDependencyError

logger = logging.getLogger(__name__)

class Resolver:
    """
    Resolves the complete, flattened build configuration for each service
    """
    def __init__(self, config: Config, images: Dict[str, Image], predefined_builds: Dict):
        self.config = config
        self.images = images
        self.predefined_builds = predefined_builds
        self.resolved_builds: Dict[str, Dict] = {}
        self.resolving_stack: set = set()

    def resolve_all(self) -> Dict[str, Dict]:
        """The main entry point to resolve all services."""
        logger.info("Resolving all build configurations...")
        for service_name in self.config.builds_config.keys():
            self._resolve_service(service_name)
        logger.info("All build configurations resolved.")
        return self.resolved_builds

    def _resolve_service(self, service_name: str) -> Dict[str, Any]:
        if service_name in self.resolved_builds:
            logger.debug(f"[Resolver] Service '{service_name}' already resolved. Returning cached config.")
            return self.resolved_builds[service_name]
        
        if service_name in self.resolving_stack: raise CircularDependencyError(f"Circular dependency in builds: '{service_name}'")
        
        logger.debug(f"[Resolver] Starting resolution for service '{service_name}'...")
        self.resolving_stack.add(service_name)
        
        if service_name not in self.config.builds_config:
            raise ConfigError(f"Build configuration for '{service_name}' not found.")
        
        service_conf = self.config.builds_config[service_name]
        ref = service_conf.get('ref')
        parent_conf = {}
        
        if ref:
            logger.debug(f"[Resolver] Service '{service_name}' has ref: '{ref}'.")
            if ':' in ref:
                software_type, role = None, None
                predefined_ref = ref
                if ref.startswith(constants.STD_BUILD_PREFIX):
                    role = ref.split(':', 1)[1]
                    image_name = service_conf.get('image')
                    if not image_name: raise ConfigError(f"Ref '{ref}' requires 'image' key for service '{service_name}'.")
                    image_obj = self.images[image_name]
                    software_type = image_obj.software
                    if not software_type: raise ConfigError(f"Image '{image_name}' has no 'software' type for ref '{ref}'.")
                    predefined_ref = f"{software_type}:{role}"
                    logger.debug(f"[Resolver] Interpreted '{ref}' as standard build '{predefined_ref}'.")
                else:
                    software_type, role = ref.split(':', 1)

                if software_type not in self.predefined_builds or role not in self.predefined_builds.get(software_type, {}):
                    raise BuildError(f"Unknown predefined build: '{predefined_ref}'.")
                parent_conf = self.predefined_builds[software_type][role]
                logger.debug(f"[Resolver] Loaded parent config from predefined build '{predefined_ref}'.")
            else:
                # Reference to another user-defined build
                logger.debug(f"[Resolver] Following reference to user-defined build '{ref}'...")
                parent_conf = self._resolve_service(ref)
                logger.debug(f"[Resolver] Parent '{ref}' resolved.")

        logger.debug(f"[Resolver] Merging parent config with child config for '{service_name}'.")
        final_conf = self._merge_configs(parent_conf, service_conf)
        if 'ref' in final_conf: del final_conf['ref']
        
        self.resolving_stack.remove(service_name)
        self.resolved_builds[service_name] = final_conf
        logger.debug(f"[Resolver] Successfully resolved service '{service_name}'. Final config: {final_conf}")
        return final_conf

    def _merge_configs(self, parent: Dict, child: Dict) -> Dict:
        merged = copy.deepcopy(parent)
        for key, value in child.items():
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                merged_set = set(merged[key])
                original_len = len(merged[key])
                merged[key].extend([item for item in value if item not in merged_set])
                # DEBUG: Log list merging details
                logger.debug(f"[Merge] Merged list for key '{key}': {original_len} parent items, {len(value)} child items -> {len(merged[key])} total unique items.")
            else:
                # DEBUG: Log value override
                if key in merged:
                    logger.debug(f"[Merge] Overriding key '{key}': from '{merged[key]}' to '{value}'.")
                else:
                    logger.debug(f"[Merge] Adding new key '{key}': '{value}'.")
                merged[key] = value
        return merged

class NetworkManager:
    """
    Manages IP address allocation and generation of Docker Compose network configuration.
    """
    def __init__(self, subnet_str: str):
        self.network = ipaddress.ip_network(subnet_str)
        self.ip_allocator = self.network.hosts()
        next(self.ip_allocator, None)
        next(self.ip_allocator, None)
        self.service_ips: Dict[str, str] = {}
        self.subnet = subnet_str

    def plan_network(self, resolved_builds: Dict) -> Dict[str, str]:
        """Allocates an IP for each service, validating any static assignments."""
        logger.info(f"Planning network for subnet {self.network}...")
        for service_name, build_conf in resolved_builds.items():
            if 'image' not in build_conf:
                logger.debug(f"Skipping IP allocation for service '{service_name}' as it has no 'image' key (likely an abstract build).")
                continue
            
            ip_address = build_conf.get('address')
            if ip_address:
                logger.debug(f"[Network] Service '{service_name}' requested static IP: {ip_address}.")
                if ipaddress.ip_address(ip_address) not in self.network:
                    raise ConfigError(f"Static IP '{ip_address}' for '{service_name}' is not in subnet '{self.network}'.")
                if ip_address in self.service_ips.values():
                    raise ConfigError(f"Static IP '{ip_address}' for '{service_name}' is already allocated.")
            else:
                try:
                    ip_address = str(next(self.ip_allocator))
                    logger.debug(f"[Network] Allocating next available dynamic IP to '{service_name}': {ip_address}.")
                except StopIteration:
                    raise BuildError(f"Subnet {self.network} is out of available IP addresses.")
            
            self.service_ips[service_name] = ip_address
        logger.debug(f"Final allocated IPs: {self.service_ips}")
        return self.service_ips
    
    def get_compose_network_block(self) -> Dict:
        """Generates the 'networks' block for the docker-compose.yml file."""
        return {
            constants.DEFAULT_NETWORK_NAME: {
                "driver": constants.DEFAULT_DEVICE_NAME,
                "ipam": {
                    "config": [{"subnet": self.subnet}]
                }
            }
        }

    
class ServiceHandler:
    """
    Handles all artifact generation for a single service.
    """
    def __init__(self, service_name: str, context: BuildContext):
        self.service_name = service_name
        self.context = context
        self.build_conf = context.resolved_builds[service_name]
        self.image_obj = context.images[self.build_conf['image']]
        self.ip = context.service_ips[service_name]
        
        self.service_dir = self.context.output_dir / self.service_name
        self.contents_dir = self.service_dir / 'contents'
        self.processed_volumes: List[str] = []
        logger.debug(f"ServiceHandler initialized for '{service_name}' with IP '{self.ip}' and image '{self.image_obj.name}'.")

    def generate_all(self) -> Dict[str, Any]:
        """Orchestrates artifact generation and returns the docker-compose service block."""
        logger.info(f"Generating artifacts for service: '{self.service_name}'...")
        self._setup_service_directory()
        self.image_obj.write(self.service_dir)
        
        main_conf_path = self._process_volumes()
        self._process_behavior(main_conf_path)
        
        compose_service_block = self._assemble_compose_service()
        logger.debug(f"Generated docker-compose block for '{self.service_name}': {compose_service_block}")
        return compose_service_block

    def _setup_service_directory(self):
        self.contents_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created service directory for '{self.service_name}' at '{self.service_dir}'")

    def _process_volumes(self) -> Path | None:
        main_conf_output_path: Path | None = None
        for volume_str in self.build_conf.get('volumes', []):
            logger.debug(f"Processing volume string for '{self.service_name}': '{volume_str}'")
            host_path_str, container_path = volume_str.rsplit(':', 1)
            filename = Path(container_path).name
            target_path = self.contents_dir / filename

            if host_path_str.startswith(constants.RESOURCE_PREFIX):
                resource_name = host_path_str[len(constants.RESOURCE_PREFIX):]
                logger.debug(f"Handling internal resource volume: '{resource_name}' -> '{target_path}'")
                try:
                    content = resources.files('dnsbuilder.resources.configs').joinpath(resource_name).read_bytes()
                    target_path.write_bytes(content)
                except FileNotFoundError:
                    raise VolumeNotFoundError(f"Internal resource for '{self.service_name}' not found: {resource_name}")
            else:
                host_path = Path(host_path_str)
                logger.debug(f"Handling file system volume: '{host_path}' -> '{target_path}'")
                if not host_path.exists():
                    raise VolumeNotFoundError(f"Volume source for '{self.service_name}' not found: {host_path}")
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
                        self.includer_factory.create(container_path, self.image_obj.software).write(str(main_conf_output_path))

            final_volume_str = f"./{self.service_name}/contents/{filename}:{container_path}"
            self.processed_volumes.append(final_volume_str)
            logger.debug(f"Added processed volume to service '{self.service_name}': {final_volume_str}")
        
        return main_conf_output_path

    def _process_behavior(self, main_conf_path: Path | None):
        behavior_str = self.build_conf.get('behavior')
        if not behavior_str: 
            logger.debug(f"Service '{self.service_name}' has no behavior to process.")
            return

        logger.debug(f"Processing behavior for '{self.service_name}'...")
        if not main_conf_path: raise BuildError(f"Service '{self.service_name}' has 'behavior' but no main .conf file.")
        if not self.image_obj.software: raise BuildError(f"Cannot process 'behavior' for '{self.service_name}': image '{self.image_obj.name}' has no 'software' type.")

        all_config_lines: Dict[str, List[str]] = {
            constants.BehaviorSection.SERVER: [], 
            constants.BehaviorSection.TOPLEVEL: []
        }

        for line in behavior_str.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'): continue
            
            logger.debug(f"Parsing behavior line: '{line}'")
            behavior_obj = self.context.behavior_factory.create(line, self.image_obj.software)
            target_ip = self.context.service_ips.get(behavior_obj.target_name)
            if not target_ip: raise BuildError(f"Behavior in '{self.service_name}' references undefined service '{behavior_obj.target_name}'.")
            
            artifact = behavior_obj.generate(self.service_name, target_ip)
            logger.debug(f"Generated behavior artifact: section='{artifact.section}', line='{artifact.config_line.replace(chr(10), ' ')}'")
            all_config_lines[artifact.section].append(artifact.config_line)

            if artifact.new_volume:
                vol = artifact.new_volume
                gen_vol_dir = self.contents_dir / constants.GENERATED_ZONES_SUBDIR
                gen_vol_dir.mkdir(exist_ok=True)
                filepath = gen_vol_dir / vol.filename
                filepath.write_text(vol.content)
                final_volume_str = f"./{self.service_name}/contents/{constants.GENERATED_ZONES_SUBDIR}/{vol.filename}:{vol.container_path}"
                self.processed_volumes.append(final_volume_str)
                logger.debug(f"Generated and added new volume from behavior: {final_volume_str}")
        
        generated_zones_content = self._format_behavior_config(all_config_lines)
        if not generated_zones_content.strip(): return

        gen_zones_path = self.contents_dir / constants.GENERATED_ZONES_FILENAME
        gen_zones_path.write_text(f"# Auto-generated by DNS Builder\n\n{generated_zones_content}\n")
        logger.debug(f"Wrote generated behavior config to '{gen_zones_path}'.")
        
        container_conf_path = f"/usr/local/etc/zones/{constants.GENERATED_ZONES_FILENAME}"
        self.processed_volumes.append(f"./{self.service_name}/contents/{constants.GENERATED_ZONES_FILENAME}:{container_conf_path}")
        
        includer = self.context.includer_factory.create(container_conf_path, self.image_obj.software)
        includer.write(str(main_conf_path))
        logger.debug(f"Appended include directive for '{container_conf_path}' to '{main_conf_path}'.")

    def _format_behavior_config(self, all_config_lines: Dict[str, List[str]]) -> str:
        content = ""
        if self.image_obj.software == constants.SOFTWARE_UNBOUND:
            if all_config_lines[constants.BehaviorSection.SERVER]:
                content += "server:\n"
                for line in all_config_lines[constants.BehaviorSection.SERVER]:
                    indented = "\n".join([f"\t{sub}" for sub in line.split('\n')])
                    content += f"{indented}\n"
            if all_config_lines[constants.BehaviorSection.TOPLEVEL]:
                content += "\n" + "\n\n".join(all_config_lines[constants.BehaviorSection.TOPLEVEL])
        else:
            all_lines = [line for section_lines in all_config_lines.values() for line in section_lines]
            content = "\n".join(all_lines)
        return content

    def _assemble_compose_service(self) -> Dict:
        logger.debug(f"Assembling final docker-compose service block for '{self.service_name}'.")
        service_config = {
            'container_name': f"{self.context.config.name}-{self.service_name}",
            'hostname': self.service_name, 'build': f"./{self.service_name}",
            'networks': {constants.DEFAULT_NETWORK_NAME: {'ipv4_address': self.ip}}
        }
        if self.processed_volumes: service_config['volumes'] = sorted(list(set(self.processed_volumes)))
        service_config['cap_add'] = self.build_conf.get('cap_add', constants.DEFAULT_CAP_ADD) or constants.DEFAULT_CAP_ADD
        for key, value in self.build_conf.items():
            if key not in constants.RESERVED_BUILD_KEYS: service_config[key] = value
        return service_config

class Builder:
    def __init__(self, config: Config):
        self.config = config
        self.output_dir = Path("output") / self.config.name
        self.predefined_builds = self._load_predefined_builds()
        logger.debug(f"Builder initialized for project '{self.config.name}'. Output dir: '{self.output_dir}'")

    def run(self):
        logger.info(f"Starting build for project '{self.config.name}'...")
        self._setup_workspace()

        # Initialization
        logger.debug("[Builder] Initialization")
        image_factory = ImageFactory(self.config.images_config)
        initial_context = BuildContext(
            config=self.config,
            images=image_factory.create_all(),
            output_dir=self.output_dir
        )
        logger.debug("[Builder] Initial build context created.")

        # Resolution
        logger.debug("[Builder] Resolution")
        resolver = Resolver(initial_context.config, initial_context.images, self.predefined_builds)
        resolved_builds = resolver.resolve_all()
        resolution_context = initial_context.model_copy(update={'resolved_builds': resolved_builds})
        logger.debug("[Builder] Build resolution complete.")

        # Network Planning
        logger.debug("[Builder] Network Planning")
        network_manager = NetworkManager(self.config.inet)
        service_ips = network_manager.plan_network(resolution_context.resolved_builds)
        final_context = resolution_context.model_copy(update={'service_ips': service_ips})
        logger.debug("[Builder] Network planning complete.")

        # Service Generation
        logger.debug("[Builder] Service Generation")
        compose_services = {}
        for name in final_context.resolved_builds.keys():
            if 'image' not in final_context.resolved_builds[name]:
                continue
            handler = ServiceHandler(name, final_context)
            compose_services[name] = handler.generate_all()
        logger.debug("[Builder] All services generated.")
         
        # Final Assembly
        logger.debug("[Builder] Final Assembly")
        compose_config = {
            "version": "3.9",
            "name": self.config.name,
            "services": compose_services,
            "networks": network_manager.get_compose_network_block()
        }
        self._write_compose_file(compose_config)
        
        logger.info(f"Build finished. Files are in '{self.output_dir}'")

    def _load_predefined_builds(self) -> Dict[str, Dict]:
        logger.debug("Loading predefined build templates...")
        try:
            templates_text = resources.files('dnsbuilder.resources.builder').joinpath('templates').read_text(encoding='utf-8')
            templates = json.loads(templates_text)
            logger.debug("Predefined build templates loaded successfully.")
            return templates
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load or parse template file: {e}"); return {}

    def _setup_workspace(self):
        if self.output_dir.exists(): 
            logger.debug(f"Output directory '{self.output_dir}' exists. Cleaning it up.")
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True)
        logger.debug(f"Workspace initialized at '{self.output_dir}'.")
    
    def _write_compose_file(self, compose_config: Dict):
        file_path = self.output_dir / constants.DOCKER_COMPOSE_FILENAME
        logger.debug(f"Writing final docker-compose configuration to '{file_path}'...")
        with file_path.open('w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)
        logger.info(f"{constants.DOCKER_COMPOSE_FILENAME} successfully generated at {file_path}")