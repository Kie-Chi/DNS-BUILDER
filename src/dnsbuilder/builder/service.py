from pathlib import Path
import shutil
import ipaddress
import logging
from typing import Dict, Any,List
from importlib import resources

from .contexts import BuildContext
from .. import constants
from ..exceptions import BuildError, VolumeNotFoundError

logger = logging.getLogger(__name__)

class ServiceHandler:
    """
    Handles all artifact generation for a single service.
    """
    def __init__(self, service_name: str, context: BuildContext):
        self.service_name = service_name
        self.context = context
        self.build_conf = context.resolved_builds[service_name]
        self.image_obj = context.images[self.build_conf['image']]
        self.ip = context.service_ips.get(service_name)
        
        self.service_dir = self.context.output_dir / self.service_name
        self.contents_dir = self.service_dir / 'contents'
        self.processed_volumes: List[str] = []
        ip_display = f"with IP '{self.ip}'" if self.ip else "with dynamic IP"
        logger.debug(f"ServiceHandler initialized for '{self.service_name}' {ip_display} and image '{self.image_obj.name}'.")

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
            
            resolved_ips = []
            for target in behavior_obj.targets:
                try:
                    ipaddress.ip_address(target)
                    resolved_ips.append(target)
                    logger.debug(f"Behavior target '{target}' is a valid IP address.")
                    continue
                except ValueError:
                    # Not a valid IP, assume it's a service name
                    pass
                
                target_ip = self.context.service_ips.get(target)
                if not target_ip:
                    raise BuildError(f"Behavior in '{self.service_name}' references an undefined service or invalid IP: '{target}'.")
                resolved_ips.append(target_ip)
                logger.debug(f"Resolved behavior target service '{target}' to IP '{target_ip}'.")

            artifact = behavior_obj.generate(self.service_name, resolved_ips)
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
        }
        if self.ip:
            service_config['networks'] = {
                constants.DEFAULT_NETWORK_NAME: {'ipv4_address': self.ip}
            }
        else:
            # with no `networks`
            pass
        if self.processed_volumes: service_config['volumes'] = sorted(list(set(self.processed_volumes)))
        service_config['cap_add'] = self.build_conf.get('cap_add', constants.DEFAULT_CAP_ADD) or constants.DEFAULT_CAP_ADD
        for key, value in self.build_conf.items():
            if key not in constants.RESERVED_BUILD_KEYS: service_config[key] = value
        return service_config
    
