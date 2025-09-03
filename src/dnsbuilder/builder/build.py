from pathlib import Path
import shutil
import yaml
import logging
import json
from typing import Dict, Optional
from importlib import resources

from .map import Mapper, GraphGenerator
from .resolve import Resolver
from .net import NetworkManager
from .service import ServiceHandler
from .contexts import BuildContext
from .. import constants
from ..config import Config
from ..images.factory import ImageFactory

logger = logging.getLogger(__name__)

class Builder:
    def __init__(self, config: Config, graph_output: Optional[str] = None):
        self.config = config
        self.graph_output = graph_output
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

        # Topology Mapping
        logger.debug("[Builder] Topology Mapping")
        mapper = Mapper(final_context.resolved_builds, final_context.service_ips)
        topology = mapper.map_topology()
        if self.graph_output:
            if GraphGenerator is None:
                pass # nothing happened
            else:
                graph_gen = GraphGenerator(topology, final_context.service_ips, self.config.name)
                graph_gen.generate_dot_file(self.graph_output)
        logger.debug("[Builder] Topology mapping complete.")

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