# build.py
import os
import shutil
import ipaddress
import yaml
import copy
import logging
import json
from typing import Dict, Any, Optional, List, Tuple
from behaviors import BehaviorFactory
from config import Config
from images import ImageFactory, Image

logger = logging.getLogger(__name__)

class Builder:
    GENERATED_ZONES_FILENAME = "generated_zones.conf"
    GENERATED_ZONES_SUBDIR = "zones" # Subdirectory for generated zonefiles/hints

    @property
    def GENERATED_ZONES_CONTAINER_PATH(self):
        return f"/usr/local/etc/{self.GENERATED_ZONES_FILENAME}"

    def __init__(self, config: Config):
        self.config = config
        self.output_dir = os.path.join("output", self.config.name)
        logger.debug(f"Builder initialized for project '{self.config.name}'. Output dir: '{self.output_dir}'")
        
        factory = ImageFactory(self.config.images_config)
        self.images = factory.create_all()

        self.network = ipaddress.ip_network(self.config.inet)
        
        self.resolved_builds: Dict[str, Dict] = {}
        self.resolving_stack_builds: set = set()
        self.service_ips: Dict[str, str] = {}
        
        self.predefined_builds = self._load_predefined_builds()
        self.behavior_factory = BehaviorFactory()

    def _load_predefined_builds(self) -> Dict[str, Dict]:
        template_path = "configs/build_templates.json"
        logger.debug(f"Attempting to load build templates from '{template_path}'...")
        if not os.path.exists(template_path):
            logger.warning(f"Template file '{template_path}' not found. No predefined builds will be available."); return {}
        try:
            with open(template_path, 'r') as f: templates = json.load(f)
            if not isinstance(templates, dict):
                logger.error(f"Template file '{template_path}' does not contain a valid JSON object."); return {}
            logger.debug(f"Successfully loaded templates for {list(templates.keys())} software types.")
            return templates
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to load or parse template file '{template_path}': {e}"); return {}

    def _merge_configs(self, parent: Dict, child: Dict) -> Dict:
        merged = copy.deepcopy(parent)
        for key, value in child.items():
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                merged[key].extend([item for item in value if item not in merged[key]])
            else:
                merged[key] = value
        return merged

    def _resolve_service(self, service_name: str) -> Dict[str, Any]:
        if service_name in self.resolved_builds: return self.resolved_builds[service_name]
        if service_name in self.resolving_stack_builds: raise ValueError(f"Circular dependency in builds: '{service_name}'")
        
        self.resolving_stack_builds.add(service_name)
        service_conf = self.config.builds_config[service_name]
        ref = service_conf.get('ref')
        parent_conf = {}
        if ref:
            if ':' in ref:
                software_type, role = None, None
                predefined_ref = ref
                if ref.startswith('std:'):
                    role = ref.split(':', 1)[1]
                    image_name = service_conf.get('image')
                    if not image_name: raise ValueError(f"Ref '{ref}' requires 'image' key for service '{service_name}'.")
                    image_obj = self.images[image_name]
                    software_type = image_obj.software
                    if not software_type: raise ValueError(f"Image '{image_name}' has no 'software' type for ref '{ref}'.")
                    predefined_ref = f"{software_type}:{role}"
                else:
                    software_type, role = ref.split(':', 1)
                if software_type not in self.predefined_builds or role not in self.predefined_builds.get(software_type, {}):
                    raise ValueError(f"Unknown predefined build: '{predefined_ref}'. Check 'configs/build_templates.json'.")
                parent_conf = self.predefined_builds[software_type][role]
            else:
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
            ip_address = build_conf.get('address') or str(next(ip_allocator))
            self.service_ips[service_name] = ip_address
            logger.debug(f"Allocated IP {ip_address} for service '{service_name}'")

    def _setup_service_directory(self, service_name: str, build_conf: Dict) -> Tuple[Image, str]:
        """Creates the output directory for a service and writes its Dockerfile."""
        logger.info(f"Processing service: '{service_name}'")
        image_obj = self.images[build_conf['image']]
        
        service_dir = os.path.join(self.output_dir, service_name)
        contents_dir = os.path.join(service_dir, 'contents')
        os.makedirs(contents_dir, exist_ok=True)
        
        image_obj.write(service_dir)
        return image_obj, contents_dir

    def _process_user_volumes(self, service_name: str, build_conf: Dict, contents_dir: str) -> Tuple[List[str], Optional[str]]:
        """Copies user-defined volumes and identifies the main configuration file."""
        processed_volumes: List[str] = []
        main_conf_output_path: Optional[str] = None

        for volume_str in build_conf.get('volumes', []):
            host_path, container_path = volume_str.split(':', 1)
            if not os.path.exists(host_path):
                raise FileNotFoundError(f"Volume source for '{service_name}' not found: {host_path}")
            
            filename = os.path.basename(host_path)
            target_path = os.path.join(contents_dir, filename)
            shutil.copy(host_path, target_path)
            
            if container_path.endswith('.conf'):
                main_conf_output_path = target_path
                logger.debug(f"Identified '{host_path}' as main config for '{service_name}'.")

            processed_volumes.append(f"./{service_name}/contents/{filename}:{container_path}")
        
        return processed_volumes, main_conf_output_path

    def _process_behavior(self, service_name: str, build_conf: Dict, image_obj: Image, contents_dir: str, main_conf_path: Optional[str], volumes: List[str]):
        """Generates artifacts from the 'behavior' key and updates volumes and config."""
        behavior_str = build_conf.get('behavior')
        if not behavior_str:
            return

        if not main_conf_path:
            raise ValueError(f"Service '{service_name}' has 'behavior' but no main .conf file was found in its volumes to include it.")
        if not image_obj.software:
            raise ValueError(f"Cannot process 'behavior' for service '{service_name}' as its image '{image_obj.name}' has no 'software' type defined.")

        all_config_lines: List[str] = []
        for line in behavior_str.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'): continue
            
            behavior_obj = self.behavior_factory.create(line, image_obj.software)
            target_ip = self.service_ips.get(behavior_obj.target_name)
            if not target_ip:
                raise ValueError(f"Behavior references undefined service '{behavior_obj.target_name}'.")
            
            artifacts = behavior_obj.generate(service_name, target_ip)
            all_config_lines.append(artifacts.config_line)

            if artifacts.new_volume:
                vol = artifacts.new_volume
                zones_dir = os.path.join(contents_dir, self.GENERATED_ZONES_SUBDIR)
                os.makedirs(zones_dir, exist_ok=True)
                filepath = os.path.join(zones_dir, vol.filename)
                with open(filepath, 'w') as f: f.write(vol.content)
                logger.info(f"Generated behavior file for '{service_name}' at '{filepath}'")
                volumes.append(f"./{service_name}/contents/{self.GENERATED_ZONES_SUBDIR}/{vol.filename}:{vol.container_path}")
        
        generated_zones_content = "\n".join(all_config_lines)
        gen_zones_path = os.path.join(contents_dir, self.GENERATED_ZONES_FILENAME)
        with open(gen_zones_path, 'w') as f:
            f.write(f"# Auto-generated by DNS Builder for '{service_name}'\n{generated_zones_content}\n")
        
        volumes.append(f"./{service_name}/contents/{self.GENERATED_ZONES_FILENAME}:{self.GENERATED_ZONES_CONTAINER_PATH}")
        
        with open(main_conf_path, 'a') as f:
            f.write(f'\n# Auto-included by DNS Builder\ninclude "{self.GENERATED_ZONES_CONTAINER_PATH}";\n')
        logger.info(f"Injected 'include' statement into '{os.path.basename(main_conf_path)}' for '{service_name}'.")

    def _assemble_compose_service(self, service_name: str, build_conf: Dict, ip_address: str, volumes: List[str]) -> Dict:
        """Constructs the final service dictionary for docker-compose.yml."""
        service_config = {
            'container_name': f"{self.config.name}-{service_name}",
            'hostname': service_name, 'build': f"./{service_name}",
            'networks': {'app_net': {'ipv4_address': ip_address}}
        }
        if volumes:
            service_config['volumes'] = volumes
        
        service_config['cap_add'] = build_conf.get('cap_add', ['NET_ADMIN']) or ['NET_ADMIN']
        
        for key, value in build_conf.items():
            if key not in ['image', 'volumes', 'cap_add', 'address', 'ref', 'behavior']:
                service_config[key] = value
        
        return service_config

    def _process_builds(self, compose_config: Dict):
        """
        Orchestrates the processing of each service to generate its configuration
        and Docker Compose definition.
        """
        self._preprocess_and_allocate_ips()
        
        logger.info("Processing resolved services for Docker Compose...")
        for service_name, build_conf in self.resolved_builds.items():
            if 'image' not in build_conf: continue

            # Step 1: Create directories and write Dockerfile
            image_obj, contents_dir = self._setup_service_directory(service_name, build_conf)
            # Step 2: Handle user-provided volumes
            processed_volumes, main_conf_path = self._process_user_volumes(
                service_name, build_conf, contents_dir
            )
            # Step 3: Handle behavior-driven configuration
            self._process_behavior(
                service_name, build_conf, image_obj, contents_dir, main_conf_path, processed_volumes
            )
            # Step 4: Assemble the final docker-compose service entry
            service_ip = self.service_ips[service_name]
            compose_config['services'][service_name] = self._assemble_compose_service(
                service_name, build_conf, service_ip, processed_volumes
            )

    def run(self):
        logger.info(f"Starting build for project '{self.config.name}'...")
        if os.path.exists(self.output_dir): shutil.rmtree(self.output_dir)
        os.makedirs(self.output_dir)
        compose_config = self._generate_compose_structure()
        self._process_builds(compose_config)
        self._write_compose_file(compose_config)
        logger.info(f"Build finished. Files are in '{self.output_dir}'")

    def _generate_compose_structure(self) -> Dict:
        return {"version": "3.9", "name": self.config.name, "services": {},
                "networks": {"app_net": {"driver": "bridge", "ipam": {"config": [{"subnet": self.config.inet}]}}}}
    
    def _write_compose_file(self, compose_config: Dict):
        file_path = os.path.join(self.output_dir, "docker-compose.yml")
        with open(file_path, 'w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False)
        logger.info(f"docker-compose.yml successfully generated at {file_path}")