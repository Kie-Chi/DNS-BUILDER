# build.py
import os
import shutil
import ipaddress
import yaml
import copy
import logging
import json
from typing import Dict, Any, Optional, List

from config import Config
from images import ImageFactory

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

    def _generate_bind_behavior_artifacts(self, service_name: str, zone: str, type: str, name: str) -> Dict[str, Any]:
        target_ip = self.service_ips.get(name)
        if not target_ip: raise ValueError(f"Behavior references undefined service '{name}'.")

        if type in ["forward", "stub"]:
            block_type = "forwarders" if type == "forward" else "masters"
            config_line = f'zone "{zone}" {{ type {type}; {block_type} {{ {target_ip}; }}; }};'
            return {'config_line': config_line, 'new_volume': None}
        elif type == "hint":
            filename = f"gen_{service_name}_root.hints"
            container_path = f"/usr/local/etc/{self.GENERATED_ZONES_SUBDIR}/{filename}"
            file_content = f".\t3600000\tIN\tNS\t{name}.\n{name}.\t3600000\tIN\tA\t{target_ip}\n"
            config_line = f'zone "{zone}" {{ type hint; file "{container_path}"; }};'
            new_volume = {'filename': filename, 'content': file_content, 'container_path': container_path}
            return {'config_line': config_line, 'new_volume': new_volume}
        else:
            raise NotImplementedError(f"BIND behavior type '{type}' is not supported.")

    def _preprocess_and_allocate_ips(self):
        logger.info("Resolving all service configurations and allocating IPs...")
        for service_name in self.config.builds_config.keys(): self._resolve_service(service_name)
        ip_allocator = self.network.hosts(); next(ip_allocator); next(ip_allocator)
        for service_name, build_conf in self.resolved_builds.items():
            if 'image' not in build_conf: continue
            ip_address = build_conf.get('address') or str(next(ip_allocator))
            self.service_ips[service_name] = ip_address
            logger.debug(f"Allocated IP {ip_address} for service '{service_name}'")

    def _process_builds(self, compose_config: Dict):
        self._preprocess_and_allocate_ips()
        
        logger.info("Processing resolved services for Docker Compose...")
        for service_name, build_conf in self.resolved_builds.items():
            if 'image' not in build_conf: continue

            logger.info(f"Processing service: '{service_name}'")
            image_obj = self.images[build_conf['image']]
            
            service_dir = os.path.join(self.output_dir, service_name)
            contents_dir = os.path.join(service_dir, 'contents')
            os.makedirs(contents_dir, exist_ok=True)
            
            image_obj.write(service_dir)

            processed_volumes: List[str] = []
            main_conf_output_path: Optional[str] = None
            
            # 1. Process USER-DEFINED volumes first. Copy them and find the main conf.
            for volume_str in build_conf.get('volumes', []):
                host_path, container_path = volume_str.split(':', 1)
                if not os.path.exists(host_path): raise FileNotFoundError(f"Volume source for '{service_name}' not found: {host_path}")
                
                filename = os.path.basename(host_path)
                target_path = os.path.join(contents_dir, filename)
                shutil.copy(host_path, target_path)
                
                if container_path.endswith('.conf'):
                    main_conf_output_path = target_path
                    logger.debug(f"Identified '{host_path}' as main config for '{service_name}'.")

                processed_volumes.append(f"./{service_name}/contents/{filename}:{container_path}")

            # 2. Process BEHAVIOR. This generates new files and config lines.
            behavior_str = build_conf.get('behavior')
            if behavior_str:
                if not main_conf_output_path:
                    raise ValueError(f"Service '{service_name}' has 'behavior' but no main .conf file was found in its volumes to include it.")
                
                all_config_lines: List[str] = []
                for line in behavior_str.strip().split('\n'):
                    line = line.strip()
                    if not line or line.startswith('#'): continue
                    parts = line.split()
                    if len(parts) != 3: raise ValueError(f"Invalid behavior for '{service_name}': '{line}'")
                    
                    artifacts = self._generate_bind_behavior_artifacts(service_name, *parts)
                    all_config_lines.append(artifacts['config_line'])

                    new_volume = artifacts.get('new_volume')
                    if new_volume:
                        zones_dir = os.path.join(contents_dir, self.GENERATED_ZONES_SUBDIR)
                        os.makedirs(zones_dir, exist_ok=True)
                        filepath = os.path.join(zones_dir, new_volume['filename'])
                        with open(filepath, 'w') as f: f.write(new_volume['content'])
                        logger.info(f"Generated behavior file for '{service_name}' at '{filepath}'")
                        processed_volumes.append(f"./{service_name}/contents/{self.GENERATED_ZONES_SUBDIR}/{new_volume['filename']}:{new_volume['container_path']}")
                
                # 3. Write the generated zones config and append the include statement.
                generated_zones_content = "\n".join(all_config_lines)
                gen_zones_path = os.path.join(contents_dir, self.GENERATED_ZONES_FILENAME)
                with open(gen_zones_path, 'w') as f:
                    f.write(f"# Auto-generated by DNS Builder for '{service_name}'\n{generated_zones_content}\n")
                
                processed_volumes.append(f"./{service_name}/contents/{self.GENERATED_ZONES_FILENAME}:{self.GENERATED_ZONES_CONTAINER_PATH}")
                
                with open(main_conf_output_path, 'a') as f:
                    f.write(f'\n# Auto-included by DNS Builder\ninclude "{self.GENERATED_ZONES_CONTAINER_PATH}";\n')
                logger.info(f"Injected 'include' statement into '{os.path.basename(main_conf_output_path)}' for '{service_name}'.")

            # 4. Assemble final service config for docker-compose.
            service_config = {
                'container_name': f"{self.config.name}-{service_name}",
                'hostname': service_name, 'build': f"./{service_name}",
                'networks': {'app_net': {'ipv4_address': self.service_ips[service_name]}}
            }
            if processed_volumes: service_config['volumes'] = processed_volumes
            service_config['cap_add'] = build_conf.get('cap_add', ['NET_ADMIN']) or ['NET_ADMIN']
            
            for key, value in build_conf.items():
                if key not in ['image', 'volumes', 'cap_add', 'address', 'ref', 'behavior']:
                    service_config[key] = value
            compose_config['services'][service_name] = service_config

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