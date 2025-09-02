# build.py
from pathlib import Path
import shutil
import ipaddress
import yaml
import copy
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from importlib import resources

from .. import constants
from ..config import Config
from .behaviors import BehaviorFactory
from .includers import IncluderFactory
from ..images.factory import ImageFactory
from ..images.image import Image
from ..exceptions import BuildError, VolumeNotFoundError, ConfigError, CircularDependencyError

logger = logging.getLogger(__name__)

class Builder:

    def __init__(self, config: Config):
        self.config = config
        self.output_dir = Path("output") / self.config.name
        logger.debug(f"Builder initialized for project '{self.config.name}'. Output dir: '{self.output_dir}'")
        
        factory = ImageFactory(self.config.images_config)
        self.images = factory.create_all()
        
        self.network = ipaddress.ip_network(self.config.inet)
        
        self.resolved_builds: Dict[str, Dict] = {}
        self.resolving_stack_builds: set = set()
        self.service_ips: Dict[str, str] = {}
        
        self.predefined_builds = self._load_predefined_builds()
        self.behavior_factory = BehaviorFactory()
        self.includer_factory = IncluderFactory()

    @property
    def GENERATED_ZONES_CONTAINER_PATH(self) -> str:
        # This can be customized per-software if needed in the future
        return f"/usr/local/etc/{constants.GENERATED_ZONES_FILENAME}"

    def _load_predefined_builds(self) -> Dict[str, Dict]:
        logger.debug("Attempting to load build templates...")
        try:
            templates_text = resources.files('dnsbuilder.resources.builder').joinpath('templates').read_text(encoding='utf-8')
            templates = json.loads(templates_text)
            if not isinstance(templates, dict):
                logger.error("Template file does not contain a valid JSON object."); return {}
            logger.debug(f"Successfully loaded templates for {list(templates.keys())} software types.")
            return templates
        except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to load or parse template file: {e}"); return {}

    def _merge_configs(self, parent: Dict, child: Dict) -> Dict:
        merged = copy.deepcopy(parent)
        for key, value in child.items():
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                # Use a set to merge lists and maintain order as much as possible
                merged_set = set(merged[key])
                merged[key].extend([item for item in value if item not in merged_set])
            else:
                merged[key] = value
        return merged

    def _resolve_service(self, service_name: str) -> Dict[str, Any]:
        if service_name in self.resolved_builds: return self.resolved_builds[service_name]
        if service_name in self.resolving_stack_builds: raise CircularDependencyError(f"Circular dependency in builds: '{service_name}'")
        
        self.resolving_stack_builds.add(service_name)
        
        if service_name not in self.config.builds_config:
            raise ConfigError(f"Build configuration for '{service_name}' not found.")
        
        service_conf = self.config.builds_config[service_name]
        ref = service_conf.get('ref')
        parent_conf = {}
        
        if ref:
            if ':' in ref:
                # Predefined build reference (e.g., "std:recursor" or "bind:recursor")
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
                else:
                    software_type, role = ref.split(':', 1)

                if software_type not in self.predefined_builds or role not in self.predefined_builds.get(software_type, {}):
                    raise BuildError(f"Unknown predefined build: '{predefined_ref}'.")
                parent_conf = self.predefined_builds[software_type][role]
            else:
                # Reference to another user-defined build
                parent_conf = self._resolve_service(ref)

        final_conf = self._merge_configs(parent_conf, service_conf)
        if 'ref' in final_conf: del final_conf['ref']
        
        self.resolving_stack_builds.remove(service_name)
        self.resolved_builds[service_name] = final_conf
        return final_conf

    def _preprocess_and_allocate_ips(self):
        logger.info("Resolving all service configurations and allocating IPs...")
        for service_name in self.config.builds_config.keys(): self._resolve_service(service_name)
        ip_allocator = self.network.hosts(); next(ip_allocator); next(ip_allocator)
        for service_name, build_conf in self.resolved_builds.items():
            if 'image' not in build_conf: continue
            
            ip_address = build_conf.get('address')
            if ip_address:
                # Validate user-provided IP
                if ipaddress.ip_address(ip_address) not in self.network:
                    raise ConfigError(f"IP address '{ip_address}' for service '{service_name}' is not in the defined subnet '{self.network}'.")
            else:
                ip_address = str(next(ip_allocator))
                
            self.service_ips[service_name] = ip_address
            logger.debug(f"Allocated IP {ip_address} for service '{service_name}'")

    def _setup_service_directory(self, service_name: str, build_conf: Dict) -> Tuple[Image, Path]:
        """Creates the output directory for a service and writes its Dockerfile."""
        logger.info(f"Processing service: '{service_name}'")
        image_obj = self.images[build_conf['image']]
        
        service_dir = self.output_dir / service_name
        contents_dir = service_dir / 'contents'
        contents_dir.mkdir(parents=True, exist_ok=True)
        
        image_obj.write(service_dir)
        return image_obj, contents_dir

    def _process_volumes(self, service_name: str, software: str, build_conf: Dict, contents_dir: Path) -> Tuple[List[str], Optional[Path]]:
        """Copies user-defined and resource volumes, and identifies the main configuration file."""
        processed_volumes: List[str] = []
        main_conf_output_path: Optional[Path] = None

        for volume_str in build_conf.get('volumes', []):
            host_path_str, container_path = volume_str.rsplit(':', 1)
            filename = Path(container_path).name
            target_path = contents_dir / filename

            if host_path_str.startswith(constants.RESOURCE_PREFIX):
                resource_name = host_path_str[len(constants.RESOURCE_PREFIX):]
                try:
                    content = resources.files('dnsbuilder.resources.configs').joinpath(resource_name).read_bytes()
                    target_path.write_bytes(content)
                    logger.debug(f"Copied internal resource '{resource_name}' to '{target_path}' for service '{service_name}'.")
                except FileNotFoundError:
                    raise VolumeNotFoundError(f"Internal resource for '{service_name}' not found: {resource_name}")
            else:
                host_path = Path(host_path_str)
                if not host_path.exists():
                    raise VolumeNotFoundError(f"Volume source for '{service_name}' not found: {host_path}")
                shutil.copy(host_path, target_path)
                logger.debug(f"Copied user volume '{host_path}' to '{target_path}' for service '{service_name}'.")
            
            if container_path.endswith('.conf'):
                if not main_conf_output_path:
                    main_conf_output_path = target_path
                    logger.debug(f"Identified '{filename}' as main config for '{service_name}'.")
                else:
                    logger.debug(f"Found additional config file '{filename}', will attempt to include it in the main config.")
                    if main_conf_output_path.read_text().find(container_path) != -1:
                        logger.debug(f"Include line for '{container_path}' already exists, skipping auto-include.")
                    else:
                        self.includer_factory.create(container_path, software).write(str(main_conf_output_path))

            processed_volumes.append(f"./{service_name}/contents/{filename}:{container_path}")
        
        return processed_volumes, main_conf_output_path

    def _process_behavior(self, service_name: str, build_conf: Dict, image_obj: Image, contents_dir: Path, main_conf_path: Optional[Path], volumes: List[str]):
        """Generates artifacts from the 'behavior' key and updates volumes and config."""
        behavior_str = build_conf.get('behavior')
        if not behavior_str:
            return

        if not main_conf_path:
            raise BuildError(f"Service '{service_name}' has 'behavior' but no main .conf file was found in its volumes to include it.")
        if not image_obj.software:
            raise BuildError(f"Cannot process 'behavior' for service '{service_name}' as its image '{image_obj.name}' has no 'software' type defined.")

        all_config_lines: Dict[str, List[str]] = {
            constants.BEHAVIOR_SECTION_SERVER: [], 
            constants.BEHAVIOR_SECTION_TOPLEVEL: []
        }

        for line in behavior_str.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'): continue
            
            behavior_obj = self.behavior_factory.create(line, image_obj.software)
            target_ip = self.service_ips.get(behavior_obj.target_name)
            if not target_ip:
                raise BuildError(f"Behavior in '{service_name}' references undefined service '{behavior_obj.target_name}'.")
            
            artifacts = behavior_obj.generate(service_name, target_ip)
            all_config_lines.setdefault(artifacts.section, []).append(artifacts.config_line)

            if artifacts.new_volume:
                vol = artifacts.new_volume
                zones_dir = contents_dir / constants.GENERATED_ZONES_SUBDIR
                zones_dir.mkdir(exist_ok=True)
                filepath = zones_dir / vol.filename
                filepath.write_text(vol.content)
                logger.info(f"Generated behavior file for '{service_name}' at '{filepath}'")
                volumes.append(f"./{service_name}/contents/{constants.GENERATED_ZONES_SUBDIR}/{vol.filename}:{vol.container_path}")
        
        generated_zones_content = ""
        if image_obj.software == constants.SOFTWARE_UNBOUND:
            if all_config_lines.get(constants.BEHAVIOR_SECTION_SERVER):
                generated_zones_content += "server:\n"
                for config_line in all_config_lines[constants.BEHAVIOR_SECTION_SERVER]:
                    indented_lines = "\n".join([f"\t{sub_line}" for sub_line in config_line.split('\n')])
                    generated_zones_content += f"{indented_lines}\n"
            
            if all_config_lines.get(constants.BEHAVIOR_SECTION_TOPLEVEL):
                generated_zones_content += "\n" + "\n\n".join(all_config_lines[constants.BEHAVIOR_SECTION_TOPLEVEL])
        else: 
            all_lines = all_config_lines.get(constants.BEHAVIOR_SECTION_TOPLEVEL, []) + all_config_lines.get(constants.BEHAVIOR_SECTION_SERVER, [])
            generated_zones_content = "\n".join(all_lines)

        if not generated_zones_content.strip():
            return

        gen_zones_path = contents_dir / constants.GENERATED_ZONES_FILENAME
        gen_zones_path.write_text(f"# Auto-generated by DNS Builder for '{service_name}'\n\n{generated_zones_content}\n")
        
        volumes.append(f"./{service_name}/contents/{constants.GENERATED_ZONES_FILENAME}:{constants.GENERATED_ZONES_SUBDIR}")
        
        includer = self.includer_factory.create(constants.GENERATED_ZONES_SUBDIR, image_obj.software)
        includer.write(str(main_conf_path))
        logger.debug(f"Injected include statement into '{main_conf_path.name}' for '{service_name}'.")

    def _assemble_compose_service(self, service_name: str, build_conf: Dict, ip_address: str, volumes: List[str]) -> Dict:
        """Constructs the final service dictionary for docker-compose.yml."""
        service_config = {
            'container_name': f"{self.config.name}-{service_name}",
            'hostname': service_name, 'build': f"./{service_name}",
            'networks': {constants.DEFAULT_NETWORK_NAME: {'ipv4_address': ip_address}}
        }
        if volumes:
            service_config['volumes'] = sorted(list(set(volumes)))
        
        service_config['cap_add'] = build_conf.get('cap_add', constants.DEFAULT_CAP_ADD) or constants.DEFAULT_CAP_ADD
        
        for key, value in build_conf.items():
            if key not in constants.RESERVED_BUILD_KEYS:
                service_config[key] = value
        
        return service_config

    def _process_builds(self) -> Dict:
        """Orchestrates the processing of each service to generate its Docker Compose definition."""
        self._preprocess_and_allocate_ips()
        
        compose_services = {}
        logger.info("Processing resolved services for Docker Compose...")
        for service_name, build_conf in self.resolved_builds.items():
            if 'image' not in build_conf: continue

            image_obj, contents_dir = self._setup_service_directory(service_name, build_conf)
            processed_volumes, main_conf_path = self._process_volumes(
                service_name, image_obj.software, build_conf, contents_dir
            )
            self._process_behavior(
                service_name, build_conf, image_obj, contents_dir, main_conf_path, processed_volumes
            )
            service_ip = self.service_ips[service_name]
            compose_services[service_name] = self._assemble_compose_service(
                service_name, build_conf, service_ip, processed_volumes
            )
        return compose_services

    def run(self):
        logger.info(f"Starting build for project '{self.config.name}'...")
        if self.output_dir.exists(): shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True)
        
        compose_config = self._generate_compose_structure()
        compose_config['services'] = self._process_builds()
        
        self._write_compose_file(compose_config)
        logger.info(f"Build finished. Files are in '{self.output_dir}'")

    def _generate_compose_structure(self) -> Dict:
        return {"version": "3.9", "name": self.config.name, "services": {},
                "networks": {constants.DEFAULT_NETWORK_NAME: {"driver": "bridge", "ipam": {"config": [{"subnet": self.config.inet}]}}}}
    
    def _write_compose_file(self, compose_config: Dict):
        file_path = self.output_dir / constants.DOCKER_COMPOSE_FILENAME
        with file_path.open('w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)
        logger.info(f"{constants.DOCKER_COMPOSE_FILENAME} successfully generated at {file_path}")