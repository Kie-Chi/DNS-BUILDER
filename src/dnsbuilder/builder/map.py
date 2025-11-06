import logging
from typing import Dict, List, Set
import ipaddress
try:
    import graphviz
except ImportError:
    graphviz = None
from ..bases.behaviors import _get_rname
from ..io.path import DNSBPath
from ..io.fs import FileSystem, AppFileSystem
from ..exceptions import DefinitionError
logger = logging.getLogger(__name__)

class Mapper:
    """
    Analyzes resolved build configurations to map the network topology
    based on service behaviors.
    """
    def __init__(self, resolved_builds: Dict, service_ips: Dict):
        self.resolved_builds = resolved_builds
        self.service_ips = service_ips
        self.topology: Dict[str, Set[str]] = {}

    def map_topology(self) -> Dict[str, List[str]]:
        """
        Parses all service behaviors to build and log the dependency graph.
        """
        logger.info("Mapping network topology based on service behaviors...")
        defined_services = set(self.resolved_builds.keys())
        for service_name, build_conf in self.resolved_builds.items():
            # Initialize an empty set for each service's dependencies
            self.topology[service_name] = set()
            
            behavior_str = build_conf.get('behavior')
            if not behavior_str:
                continue

            for line in behavior_str.strip().split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split(maxsplit=2)
                if len(parts) < 2 :  # Allow behaviors like 'master' that might not have targets initially
                    logger.warning(
                        f"Could not parse behavior line for topology mapping: '{line}' in service '{service_name}'"
                    )
                    continue

                record, behavior_type, args_str = (parts + [""])[:3]
                record = record.rstrip(".") + "."
                targets_str = ""
                if behavior_type == "master":
                    if args_str:
                        # For master, format is: <record-name> <type> [<ttl>] <target1> ,<target2> ...
                        master_args = args_str.split(maxsplit=3)
                        if len(master_args) >= 4:
                            # solve the ttl or unexpected space between targets
                            try:
                                int(master_args[2])
                                targets_str = master_args[3]
                            except Exception:
                                targets_str = args_str.split(maxsplit=2)[-1]
                                pass
                        elif len(master_args) == 3:
                            targets_str = master_args[-1] # The third part is the actual target list
                else:
                    targets_str = args_str

                if not targets_str:
                    continue  # No targets to map for this line

                targets = [t.strip() for t in targets_str.split(",")]

                for target in targets:
                    # Check if the target is a defined service or an external IP
                    is_ip = False
                    try:
                        ipaddress.ip_address(target)
                        is_ip = True
                    except ValueError:
                        pass # It's not an IP, assume it's a service name

                    if not is_ip and target not in defined_services:
                        target = _get_rname(target, record)
                        logger.warning(
                            f"Service '{service_name}' has a behavior targeting an "
                            f"undefined service or invalid name: '{target}'"
                        )
                    
                    self.topology[service_name].add(target)
        final_topology = {
            source: sorted(list(targets))
            for source, targets in self.topology.items()
        }

        self._log_topology(final_topology)
        return final_topology

    def _log_topology(self, topology_data: Dict[str, List[str]]):
        """Logs the generated topology in a readable format."""
        logger.debug("--- Network Topology ---")
        if not topology_data:
            logger.debug("No explicit service relationships found in behaviors.")
            logger.debug("------------------------")
            return

        for source, targets in topology_data.items():
            source_ip = self.service_ips.get(source, "Dynamic/IP")
            logger.debug(f"  - Service: {source} ({source_ip})")
            for target in targets:
                # Check if the target is another service we know or an external entity
                target_ip = self.service_ips.get(target, "External/IP")
                logger.debug(f"    -> {target} ({target_ip})")
        logger.debug("------------------------")

class GraphGenerator:
    """
    Generates a Graphviz DOT file from network topology data.
    """
    def __init__(self, topology_data: Dict[str, List[str]], service_ips: Dict[str, str], project_name: str, fs: FileSystem = None):
        if graphviz is None:
            raise ImportError("The 'graphviz' library is required to generate graphs. Please install it (`pip install graphviz`).")
        
        self.topology = topology_data
        self.service_ips = service_ips
        self.project_name = project_name
        if fs is None:
            raise DefinitionError("FileSystem is not provided.")
        self.fs = fs

    def generate_dot_file(self, output_path: str):
        """
        Creates and saves the DOT graph file.
        """
        dot = graphviz.Digraph(
            self.project_name,
            comment=f'DNSBuilder Topology for {self.project_name}',
            graph_attr={'rankdir': 'LR', 'splines': 'true', 'overlap': 'false', 'fontsize': '12'},
            node_attr={'shape': 'box', 'style': 'rounded,filled', 'fillcolor': '#e8f4ff'},
            edge_attr={'color': '#4a4a4a'}
        )

        all_nodes: Set[str] = set(self.topology.keys()).union(*[set(v) for v in self.topology.values()])
        for node_name in sorted(list(all_nodes)):
            if node_name in self.service_ips:
                ip = self.service_ips[node_name]
                label = f"{node_name}\\n({ip})"
                dot.node(node_name, label=label)
            else:
                dot.node(node_name, label=node_name, shape='ellipse', fillcolor='#f0f0f0')
        for source, targets in self.topology.items():
            for target in targets:
                dot.edge(source, target)
        output_file = DNSBPath(output_path)
        self.fs.mkdir(output_file.parent, parents=True, exist_ok=True)
        self.fs.write_text(output_file, dot.source)
        logger.info(f"Network topology graph written to '{output_file}'")