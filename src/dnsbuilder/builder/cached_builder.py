import logging
from typing import Dict, Optional
import asyncio

from .build import Builder
from ..cache import CacheManager, ProjectCacheView, ServiceCacheView
from .. import constants
from ..datacls import BuildContext
from ..config import Config
from ..io import FileSystem, DNSBPath, create_app_fs
from ..exceptions import DefinitionError
logger = logging.getLogger(__name__)


class CachedBuilder(Builder):
    """
    CachedBuilder supports incremental builds by caching service metadata.
    
    It first builds the project to a HyperMemoryFileSystem, then compares the
    cached service metadata with the new build results to determine which services
    need to be rebuilt. Only the changed services are then synchronized to the
    real project directory.
    """
    
    def __init__(self, config: Config, graph_output: Optional[str] = None, fs: FileSystem = None, cache_dir: DNSBPath = DNSBPath(".dnsb_cache")):
        if fs is None:
            raise DefinitionError("FileSystem is not provided.")
        # Init parent class with real file system
        super().__init__(config, graph_output, fs)
        self.real_fs = fs
        self.cache_manager = CacheManager(fs, cache_dir)
        
        self.memory_fs = create_app_fs(use_vfs=True, enable_fallback=True, chroot=fs.chroot)
        
        self.project_cache: Optional[ProjectCacheView] = None
        self.memory_project_cache: Optional[ProjectCacheView] = None
        
    async def run(self):
        """run with cache"""
        logger.info(f"Starting cached build for project '{self.config.name}'...")
        
        # Step 1: load existing cache
        self._load_existing_cache()
        
        # Step 2: check consistency if cache exists
        cache_consistent = self._check_cache_consistency()
        
        # Step 3: build in memory
        context = await self._build_in_memory()
        
        # Step 4: generate memory cache view from build result
        self._generate_memory_cache_view(context)
        
        # Step 5: compare memory cache with existing cache
        if cache_consistent:
            changes = self._compare_caches()
        else:
            logger.info("Cache inconsistent, performing full rebuild")
            changes = {
                'services_to_update': set(self.memory_project_cache.services.keys()),
                'services_to_remove': set(),
                'docker_compose_changed': True
            }
        
        # Step 6: sync changes to disk
        self._sync_change(changes)
        
        # Step 7: save updated cache
        self._save_updated_cache()
        
        logger.info(f"Cached build finished. Files are in '{self.output_dir}'")
    
    def _check_cache_consistency(self) -> bool:
        """Check if cache is consistent with output directory
        
        Returns:
            bool: True if cache is consistent or no cache exists, False if inconsistent
        """
        if not self.project_cache:
            logger.debug("No existing cache to check consistency")
            return True
        
        logger.debug("Checking cache consistency with output directory...")
        is_consistent = self.cache_manager.check_project_consistency(
            self.project_cache, 
            self.output_dir
        )
        
        if is_consistent:
            logger.info("Cache is consistent with output directory")
        else:
            logger.warning("Cache is inconsistent with output directory")
        
        return is_consistent

    def _load_existing_cache(self):
        """load existing project cache"""
        logger.debug("Loading existing project cache...")
        self.project_cache = self.cache_manager.load_project_cache(self.config.name)
        if self.project_cache:
            logger.info("Loaded existing project cache")
        else:
            logger.info("No existing cache found")
    
    async def _build_in_memory(self) -> BuildContext:
        """build project in memory file system, return BuildContext"""
        logger.info("Building project in memory...")
        memory_builder = Builder(self.config, self.graph_output, self.memory_fs)
        context = await memory_builder.run(need_context=True)
        
        if hasattr(self.memory_fs, '_fallback_stats'):
            stats = self.memory_fs._fallback_stats
            if stats['count'] > 0:
                logger.info(
                    f"Memory build used disk fallback {stats['count']} times "
                    f"for {len(stats['paths'])} unique files"
                )
                logger.debug(f"Fallback operations breakdown: {stats['operations']}")
                # Log individual fallback paths at debug level
                for path in sorted(stats['paths']):
                    logger.debug(f"  - Read from disk via fallback: {path}")
        
        logger.info("Memory build completed")
        return context
    
    def _generate_memory_cache_view(self, context: BuildContext):
        """generate cache view from memory build result"""
        logger.debug("Generating cache view from BuildContext...")
        memory_output_dir = DNSBPath("output") / self.config.name
        
        self.memory_project_cache = ProjectCacheView(
            name=self.config.name,
            proj_config=self.config.model.model_dump(by_alias=True, exclude_none=True),
            services={},
            output_dir=str(memory_output_dir)
        )
        
        # scan services
        for service_name, service_config in context.resolved_builds.items():
            logger.debug(f"Processing service: {service_name}")
            service_dir = memory_output_dir / service_name
            service_cache = ServiceCacheView(
                name=service_name,
                build_config=service_config,
                ip=context.service_ips.get(service_name),
                files={}
            )
            
            if self.memory_fs.exists(service_dir) and self.memory_fs.is_dir(service_dir):
                service_cache.scan(service_dir, self.memory_fs, is_ignore=True)
            else:
                logger.warning(f"Service directory not found in memory: {service_dir}")
            
            self.memory_project_cache.add_service(service_cache)
        
        # docker-compose hash
        docker_compose_path = memory_output_dir / constants.DOCKER_COMPOSE_FILENAME
        if self.memory_fs.exists(docker_compose_path):
            self.memory_project_cache.set_docker_compose_hash(
                self.memory_project_cache.calculate_docker_compose_hash(docker_compose_path, self.memory_fs)
            )
        
        logger.debug(f"Memory cache view generated for {len(context.resolved_builds)} services")
    
    def _compare_caches(self) -> Dict[str, str]:
        """Compare memory cache with existing cache, return changes
        
        Returns:
            Dict with keys:
            - services_to_update: set of service names that need update
            - services_to_remove: set of service names that need remove
            - docker_compose_changed: bool if docker-compose file changed
        """
        logger.debug("Comparing memory cache with existing cache...")
        
        changes = {
            'services_to_update': set(),
            'services_to_remove': set(),
            'docker_compose_changed': False,
        }
        
        if not self.project_cache:
            # all content will be updated
            logger.info("No existing cache, all content will be updated")
            changes['services_to_update'] = set(self.memory_project_cache.services.keys())
            changes['docker_compose_changed'] = True
            return changes
        
        # compare docker-compose file
        if self.project_cache.docker_compose_hash != self.memory_project_cache.docker_compose_hash:
            logger.debug("Docker-compose file changed")
            changes['docker_compose_changed'] = True
        
        # compare services
        memory_services = set(self.memory_project_cache.services.keys())
        existing_services = set(self.project_cache.services.keys())
        
        # check services to update
        for service_name in memory_services:
            memory_service = self.memory_project_cache.get_service(service_name)
            existing_service = self.project_cache.get_service(service_name)
            
            if not existing_service:
                # new service
                logger.debug(f"New service detected: {service_name}")
                changes['services_to_update'].add(service_name)
            elif memory_service.get_update_hash() != existing_service.get_update_hash():
                # service changed
                logger.debug(f"Service changed: {service_name}")
                changes['services_to_update'].add(service_name)
        
        # check services to remove
        changes['services_to_remove'] = existing_services - memory_services
        if changes['services_to_remove']:
            logger.debug(f"Services to remove: {list(changes['services_to_remove'])}")
        
        logger.debug(f"Cache comparison complete. Services to update: {len(changes['services_to_update'])}, "
                   f"Services to remove: {len(changes['services_to_remove'])}, "
                   f"Docker-compose changed: {changes['docker_compose_changed']}")
        
        return changes
    
    def _sync_change(self, changes: Dict):
        """sync changes to disk"""
        logger.info("Syncing changes to disk...")
        
        # ensure output directory exists
        if not self.real_fs.exists(self.output_dir):
            self.real_fs.mkdir(self.output_dir, parents=True)
            logger.debug(f"Created output directory: {self.output_dir}")
        
        # ensure memory output directory exists
        memory_output_dir = DNSBPath("output") / self.config.name
        if not self.memory_fs.exists(memory_output_dir):
            self.memory_fs.mkdir(memory_output_dir, parents=True)
            logger.debug(f"Created memory output directory: {memory_output_dir}")
        
        # remove services to remove
        for service_name in changes['services_to_remove']:
            service_dir = self.output_dir / service_name
            if self.real_fs.exists(service_dir):
                self.real_fs.rmtree(service_dir)
                logger.info(f"Removed service directory: {service_name}")
        
        # sync services to update
        for service_name in changes['services_to_update']:
            self._sync_service(service_name, memory_output_dir)
        
        # sync docker-compose file (if changed)
        if changes['docker_compose_changed']:
            self._sync_compose(memory_output_dir)
        
        logger.info("Changes synced to disk successfully")
    
    def _sync_service(self, service_name: str, memory_output_dir: DNSBPath):
        """update service to disk using FileCacheView"""
        logger.debug(f"Syncing service '{service_name}' to disk using FileCacheView...")
        
        memory_service_dir = memory_output_dir / service_name
        real_service_dir = self.output_dir / service_name
        if not self.memory_fs.exists(memory_service_dir):
            logger.warning(f"Service directory not found in memory: {service_name}")
            return

        memory_service_cache = self.memory_project_cache.get_service(service_name)
        if not memory_service_cache:
            logger.warning(f"Service cache view not found for: {service_name}, falling back to recursive copy")
            # Fallback: use recursive file-by-file copy to avoid cross-filesystem issues
            if self.real_fs.exists(real_service_dir):
                self.real_fs.rmtree(real_service_dir)
            self._copy_directory_recursive(memory_service_dir, real_service_dir)
            logger.info(f"Service '{service_name}' synced using recursive copy fallback")
            return
        
        if not self.real_fs.exists(real_service_dir):
            self.real_fs.mkdir(real_service_dir, parents=True)
        existing_service_cache = None
        if self.project_cache:
            existing_service_cache = self.project_cache.get_service(service_name)
        
        files_synced = 0
        files_skipped = 0
        
        # all files in memory_service_cache
        for rel_file_path, memory_file_cache in memory_service_cache.files.items():
            memory_file_path = memory_service_dir / rel_file_path
            real_file_path = real_service_dir / rel_file_path
            
            # check if file needs sync
            needs_sync = True
            
            if existing_service_cache and rel_file_path in existing_service_cache.files:
                existing_file_cache = existing_service_cache.files[rel_file_path]
                # check if file content has changed
                if (memory_file_cache.get_update_hash() == existing_file_cache.get_update_hash() and
                    self.real_fs.exists(real_file_path)):
                    needs_sync = False
                    files_skipped += 1
            
            if needs_sync:
                # ensure target directory exists
                real_file_dir = real_file_path.parent
                if not self.real_fs.exists(real_file_dir):
                    self.real_fs.mkdir(real_file_dir, parents=True)
                
                # copy file
                if self.memory_fs.exists(memory_file_path):
                    file_content = self.memory_fs.read_bytes(memory_file_path)
                    self.real_fs.write_bytes(real_file_path, file_content)
                    files_synced += 1
                    logger.debug(f"Synced file: {rel_file_path}")
                else:
                    logger.warning(f"File not found in memory: {memory_file_path}")
        
        # delete obsolete files
        if existing_service_cache:
            for rel_file_path in existing_service_cache.files.keys():
                if rel_file_path not in memory_service_cache.files:
                    real_file_path = real_service_dir / rel_file_path
                    if self.real_fs.exists(real_file_path):
                        self.real_fs.remove(real_file_path)
                        logger.debug(f"Removed obsolete file: {rel_file_path}")
        
        logger.info(f"Service '{service_name}' synced: {files_synced} files updated, {files_skipped} files skipped")
    
    def _sync_compose(self, memory_output_dir: DNSBPath):
        """sync docker-compose file to disk"""
        logger.debug("Syncing docker-compose file to disk...")
        
        memory_compose_path = memory_output_dir / constants.DOCKER_COMPOSE_FILENAME
        real_compose_path = self.output_dir / constants.DOCKER_COMPOSE_FILENAME
        
        if self.memory_fs.exists(memory_compose_path):
            compose_content = self.memory_fs.read_bytes(memory_compose_path)
            self.real_fs.write_bytes(real_compose_path, compose_content)
            logger.info("Docker-compose file updated")
        else:
            logger.warning("Docker-compose file not found in memory build")
        
    def _save_updated_cache(self):
        """save updated cache to disk"""
        logger.debug("Saving updated cache...")
        
        if self.memory_project_cache:
            # update timestamp
            self.memory_project_cache.update_timestamp()
            
            # save cache
            success = self.cache_manager.save_project_cache(self.memory_project_cache)
            if success:
                logger.info("Updated cache saved successfully")
            else:
                logger.warning("Failed to save updated cache")
        else:
            logger.warning("No memory cache to save")
    
    def get_cache_stats(self) -> Optional[Dict]:
        """get cache statistics"""
        return self.cache_manager.get_cache_stats(self.config.name)
    
    def clear_cache(self) -> bool:
        """clear project cache"""
        return self.cache_manager.delete_project_cache(self.config.name)
    
    def _copy_directory_recursive(self, src_dir: DNSBPath, dst_dir: DNSBPath):
        """recursively copy directory, avoiding cross-filesystem copytree issues"""
        if not self.memory_fs.exists(src_dir):
            return
        
        self.real_fs.mkdir(dst_dir, parents=True)
        for item in self.memory_fs.listdir(src_dir):
            src_item = src_dir / item.name
            dst_item = dst_dir / item.name
            
            if self.memory_fs.is_dir(src_item):
                self._copy_directory_recursive(src_item, dst_item)
            else:
                try:
                    content = self.memory_fs.read_bytes(src_item)
                    self.real_fs.write_bytes(dst_item, content)
                except Exception as e:
                    logger.warning(f"Failed to copy file {src_item} to {dst_item}: {e}")