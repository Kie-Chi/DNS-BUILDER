import ipaddress
import logging
from typing import Dict

from .. import constants
from ..exceptions import BuildError, ConfigError

logger = logging.getLogger(__name__)

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