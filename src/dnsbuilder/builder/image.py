"""
Image Builder Module

Handles shared image builder service generation for Docker Compose.
This module implements the "builder service pattern" to avoid parallel build conflicts
while enabling efficient image reuse across multiple services.
"""

import logging
from typing import Dict, Any, Set, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SharedImageInfo:
    """Information about a shared image and its consumers"""
    image_tag: str
    build_context: str
    image_hash: str
    consumers: Set[str] = field(default_factory=set)
    
    def get_name(self) -> str:
        """Generate builder service name from image hash"""
        # Use first 8 chars of hash for readability
        return f"dnsb-image-builder-{self.image_hash[:8]}"
    
    def add_consumer(self, service_name: str):
        """Add a service that uses this shared image"""
        self.consumers.add(service_name)


class ImageBuilder:
    """
    Manages shared image builder services for Docker Compose.
    
    This class implements the builder service pattern:
    - Each unique shared image gets one builder service
    - Builder services have build config and image tag
    - Builder services use 'donotstart' profile (won't run)
    - Consumer services reference image + depend on builder
    - Docker Compose builds each image once, consumers reuse it
    """
    
    def __init__(self):
        self.shared_images: Dict[str, SharedImageInfo] = {}
        logger.debug("ImageBuilder initialized")
    
    def reg_img(self, image_tag: str, build_context: str, image_hash: str, service_name: str):
        """
        Register a shared image and its consumer service.
        
        Args:
            image_tag: Full image tag (e.g., dnsb-bind-9.18.4-3dd6ed5f9dedb1e7)
            build_context: Build context path (e.g., ./.images/3dd6ed5f9dedb1e7)
            image_hash: Image content hash
            service_name: Name of the service using this image
        """
        if image_tag not in self.shared_images:
            self.shared_images[image_tag] = SharedImageInfo(
                image_tag=image_tag,
                build_context=build_context,
                image_hash=image_hash
            )
            logger.debug(f"Registered new shared image: {image_tag}")
        
        self.shared_images[image_tag].add_consumer(service_name)
        logger.debug(f"Added consumer '{service_name}' to shared image '{image_tag}'")
    
    def gen_srv(self) -> Dict[str, Dict[str, Any]]:
        """
        Generate builder service configurations for all shared images.
        
        Returns:
            Dictionary of builder service configurations keyed by service name
        """
        builder_services = {}
        
        for image_info in self.shared_images.values():
            builder_name = image_info.get_name()
            
            builder_config = {
                'build': {
                    'context': image_info.build_context,
                    # Use cache_from to leverage existing images
                    'cache_from': [f"{image_info.image_tag}:latest"]
                },
                'image': f"{image_info.image_tag}:latest",
                'command': ["true"]
            }
            
            builder_services[builder_name] = builder_config
            
            logger.info(
                f"Generated builder service '{builder_name}' for image '{image_info.image_tag}' "
                f"(consumers: {', '.join(sorted(image_info.consumers))})"
            )
        
        return builder_services
    
    def get_deps(self, image_tag: str) -> str:
        """
        Get the builder service name for a given image tag.
        
        Args:
            image_tag: The image tag to lookup
            
        Returns:
            Builder service name that should be added to depends_on
        """
        if image_tag not in self.shared_images:
            raise ValueError(f"Image tag '{image_tag}' not registered")
        
        return self.shared_images[image_tag].get_name()
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of all shared images and their usage.
        
        Returns:
            Dictionary with statistics and details
        """
        summary = {
            'total_shared_images': len(self.shared_images),
            'total_consumers': sum(len(img.consumers) for img in self.shared_images.values()),
            'images': []
        }
        
        for image_info in self.shared_images.values():
            summary['images'].append({
                'tag': image_info.image_tag,
                'builder': image_info.get_name(),
                'context': image_info.build_context,
                'hash': image_info.image_hash,
                'consumers': sorted(image_info.consumers),
                'consumer_count': len(image_info.consumers)
            })
        
        return summary
