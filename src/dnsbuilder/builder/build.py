import yaml
import logging
import json
from typing import Dict, Optional

from ..factories import ImageFactory
from ..base import Image
from ..bases.external import SelfDefinedImage, DockerImage
from ..datacls.contexts import BuildContext
from .map import Mapper, GraphGenerator
from .substitute import VariableSubstitutor
from .resolve import Resolver
from .net import NetworkManager
from .service import ServiceHandler
from .. import constants
from ..config import Config
from ..io.path import DNSBPath
from ..io.fs import FileSystem, AppFileSystem
from ..exceptions import BuildError, DNSBuilderError, ImageDefinitionError

logger = logging.getLogger(__name__)

class Builder:

    def __init__(self, config: Config, graph_output: Optional[str] = None, fs: FileSystem = AppFileSystem()):
        self.config = config
        self.graph_output = graph_output
        self.fs = fs
        self.output_dir = DNSBPath("output") / self.config.name
        self.predefined_builds = self._load_predefined_builds()
        self.image_cache: Dict[str, Image] = {}
        logger.debug(f"Builder initialized for project '{self.config.name}'. Output dir: '{self.output_dir}'")

    def run(self, need_context: bool = False) -> Optional[BuildContext]:
        """Orchestrates the entire build process step by step."""
        logger.info(f"Starting build for project '{self.config.name}'...")
        self._setup_workspace()

        # Step 1: Initialize context and resolve all defined images from the 'images' block.
        context = self._initialize_context()

        # Step 2: Resolve all service build configurations, handling inheritance and mixins.
        resolved_builds = self._resolve_builds(context)
        context = context.model_copy(update={'resolved_builds': resolved_builds})
        
        # Step 3: Resolve all images referenced in services.
        context = self._resolve_service_images(context)

        # Step 4: Plan network addresses for all services.
        service_ips = self._plan_network(context)
        context = context.model_copy(update={'service_ips': service_ips})

        # Step 5: Substitute variables (like ${name}, ${ip}) in the resolved configurations.
        substituted_builds = self._substitute_variables(context)
        context = context.model_copy(update={'resolved_builds': substituted_builds})

        # Step 6: Map the network topology and generate a graph if requested.
        self._map_topology(context)

        # Step 7: Generate artifacts (Dockerfiles, configs) for each service.
        compose_services = self._generate_services(context)

        # Step 8: Assemble the final docker-compose.yml file and write it to disk.
        self._assemble_and_write_compose(compose_services, context)
        
        logger.info(f"Build finished. Files are in '{self.output_dir}'")
        if need_context:
            return context
        return None

    def _initialize_context(self) -> BuildContext:
        """Creates the initial build context and resolves images defined in the config."""
        logger.debug("[Builder] Step 1: Initializing context...")
        image_factory = ImageFactory(self.config.images_config, self.fs)
        resolved_images = image_factory.create_all()
        self.image_cache.update(resolved_images) # Cache the explicitly defined images
        
        context = BuildContext(
            config=self.config,
            images=resolved_images,
            output_dir=self.output_dir,
            fs=self.fs
        )
        logger.debug("[Builder] Initial build context created.")
        return context

    def _resolve_builds(self, context: BuildContext) -> Dict:
        """Resolves the flattened configuration for each service."""
        logger.debug("[Builder] Step 2: Resolving build configurations...")
        resolver = Resolver(context.config, context.images, self.predefined_builds)
        resolved_builds = resolver.resolve_all()
        resolved_builds = {key : value for key, value in resolved_builds.items() if value.get("build")}
        logger.debug("[Builder] Build resolution complete.")
        return resolved_builds

    def _plan_network(self, context: BuildContext) -> Dict[str, str]:
        """Allocates IP addresses to services."""
        logger.debug("[Builder] Step 4: Planning network...")
        network_manager = NetworkManager(self.config.inet)
        service_ips = network_manager.plan_network(context.resolved_builds)
        logger.debug("[Builder] Network planning complete.")
        return service_ips

    def _substitute_variables(self, context: BuildContext) -> Dict:
        """Performs variable substitution across all resolved build configs."""
        logger.debug("[Builder] Step 5: Substituting variables...")
        substitutor = VariableSubstitutor(
            config=context.config, 
            images=context.images, 
            service_ips=context.service_ips,
            resolved_builds=context.resolved_builds
        )
        substituted_builds = substitutor.run(context.resolved_builds)
        logger.debug("[Builder] Variable substitution complete.")
        return substituted_builds

    def _map_topology(self, context: BuildContext):
        """Analyzes service behaviors to map the network topology."""
        logger.debug("[Builder] Step 6: Mapping topology...")
        mapper = Mapper(context.resolved_builds, context.service_ips)
        topology = mapper.map_topology()
        if self.graph_output:
            if GraphGenerator is None:
                logger.warning("Graphviz library not found, skipping graph generation.")
            else:
                graph_gen = GraphGenerator(topology, context.service_ips, self.config.name, self.fs)
                graph_gen.generate_dot_file(self.graph_output)
        logger.debug("[Builder] Topology mapping complete.")

    def _resolve_service_images(self, context: BuildContext) -> BuildContext:
        """
        Ensures all images referenced by services are resolved and cached.
        This includes images not explicitly defined in the top-level 'images' block.
        """
        logger.debug("[Builder] Step 3: Resolving service images...")
        for name, conf in context.resolved_builds.items():
            image_name = conf.get('image')
            if image_name:
                # This will resolve and cache the image if not already present.
                self._get_image_for_service(image_name)

        # Update the context with the full image cache
        updated_context = context.model_copy(update={'images': self.image_cache})
        logger.debug("[Builder] Service image resolution complete.")
        return updated_context

    def _get_image_for_service(self, image_name: str) -> Image:
        """
        Resolves an image name string to an Image object.
        Handles internal, local, and remote images.
        """
        if image_name in self.image_cache:
            return self.image_cache[image_name]

        # Try to resolve as SelfDefinedImage first.
        try:
            logger.debug(f"Image '{image_name}' resolved as a self-defined build context path.")
            config = {"name": image_name, "ref": image_name}
            image_obj = SelfDefinedImage(config, fs=self.fs)
            self.image_cache[image_name] = image_obj
            return image_obj
        except (TypeError, ValueError, OSError, DNSBuilderError):
            # Not a SelfDefinedImage
            pass
        except Exception:
            # error
            raise

        # Default to DockerImage.
        logger.debug(f"Image '{image_name}' resolved as a Docker image.")
        config = {"name": image_name, "ref": image_name}
        image_obj = DockerImage(config, fs=self.fs)
        self.image_cache[image_name] = image_obj
        return image_obj

    def _generate_services(self, context: BuildContext) -> Dict[str, Dict]:
        """Generates all artifacts for each buildable service."""
        logger.debug("[Builder] Step 7: Generating services...")
        compose_services = {}
        buildable_services = {
            name: conf for name, conf in context.resolved_builds.items()
            if conf.get('build', True)
        }
        logger.info(f"Found {len(buildable_services)} buildable services.")

        for name, conf in buildable_services.items():
            logger.debug(f"Handling buildable service: '{name}'")
            if 'image' not in conf:
                raise ImageDefinitionError(f"Buildable service '{name}' is missing the required 'image' key.")

            handler = ServiceHandler(name, context)
            compose_services[name] = handler.generate_all()
        
        logger.debug("[Builder] All services generated.")
        return compose_services
         
    def _assemble_and_write_compose(self, services: Dict, context: BuildContext):
        """Assembles the final docker-compose dictionary and writes it to a YAML file."""
        logger.debug("[Builder] Step 8: Assembling final docker-compose file...")
        compose_config = {
            "version": "3.9",
            "name": self.config.name,
            "services": services,
            "networks": NetworkManager(self.config.inet).get_compose_network_block()
        }
        
        all_config_data = self.config.model.model_dump()
        extra_config = {
            key: value for key, value in all_config_data.items() 
            if key not in constants.RESERVED_CONFIG_KEYS
        }
        if extra_config:
            logger.debug(f"Adding extra top-level configurations to docker-compose: {list(extra_config.keys())}")
            compose_config.update(extra_config)

        self._write_compose_file(compose_config)

    def _load_predefined_builds(self) -> Dict[str, Dict]:
        logger.debug("Loading predefined build templates...")
        try:
            templates_path = DNSBPath("resource:/builder/templates")
            templates_text = self.fs.read_text(templates_path)
            templates = json.loads(templates_text)
            logger.debug("Predefined build templates loaded successfully.")
            return templates
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise BuildError(f"Failed to load or parse template file: {e}")

    def _setup_workspace(self):
        if self.fs.exists(self.output_dir): 
            logger.debug(f"Output directory '{self.output_dir}' exists. Cleaning it up.")
            self.fs.rmtree(self.output_dir)
        self.fs.mkdir(self.output_dir, parents=True)
        logger.debug(f"Workspace initialized at '{self.output_dir}'.")
    
    def _write_compose_file(self, compose_config: Dict):
        file_path = self.output_dir / constants.DOCKER_COMPOSE_FILENAME
        logger.debug(f"Writing final docker-compose configuration to '{file_path}'...")
        content = yaml.dump(compose_config, default_flow_style=False, sort_keys=False)
        self.fs.write_text(file_path, content)
        logger.info(f"{constants.DOCKER_COMPOSE_FILENAME} successfully generated at {file_path}")
