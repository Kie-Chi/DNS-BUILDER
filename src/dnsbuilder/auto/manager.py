import logging
from typing import Any, Dict, List, Optional, Union
import os

from .executor import ScriptExecutor
from ..io import FileSystem
from ..exceptions import UnsupportedFeatureError

logger = logging.getLogger(__name__)


class AutomationManager:
    """Manager for orchestrating automation phases."""
    
    def __init__(self, max_workers: Optional[int] = None, fs: Optional[FileSystem] = None):
        """
        Initialize the automation manager.
        
        Args:
            max_workers: Maximum number of worker processes
            fs: File system instance to pass to ScriptExecutor
        """
        self.executor = ScriptExecutor(max_workers, fs)
        if max_workers is None:
            max_workers = os.cpu_count() or 1
        self.max_workers = max_workers
    
    def setup(self, config: Dict[str, Any]) -> None:
        """
        Execute the setup phase.
        
        Args:
            config: Full configuration object
            
        Returns:
            Modified configuration
        """
        logger.info(f"[Auto@{self.max_workers}] Starting setup phase")
        
        # Get automation config
        auto_config = config.get('auto', {})
        global_setup = auto_config.pop('setup', None)
        current_config = config
        if global_setup:
            if isinstance(global_setup, str):
                # Single script
                logger.info(f"[Auto@{self.max_workers}] Executing global setup script: {global_setup[:20]}...")
                current_config = self.executor.execute_script(
                    global_setup,
                    'python',
                    current_config
                )
            else:
                logger.info(f"[Auto@{self.max_workers}] Executing {len(global_setup)} global setup scripts serially")
                for i, script in enumerate(self._normalize_scripts(global_setup)):
                    current_config = self.executor.execute_script(
                        script.get('content', ""),
                        script.get('type', 'python'),
                        current_config
                    )
        else:
            logger.debug(f"[Auto@{self.max_workers}] No global setup script found")
        
        service_scripts = []
        builds = current_config.get('builds', {})
        
        for service_name, build_config in builds.items():
            # Skip services with build: false (templates)
            if not build_config.get('build', True):
                logger.debug(f"[Auto@{self.max_workers}] Skipping setup for service '{service_name}' (build=false)")
                continue
                
            service_auto = build_config.get('auto', {})
            service_setup = service_auto.pop('setup', None)
            
            if service_setup:
                if isinstance(service_setup, str):
                    # Single script
                    service_scripts.append({
                        'content': service_setup,
                        'type': 'python',
                        'service_name': service_name
                    })
                else:
                    normal_scripts = self._normalize_scripts(service_setup)
                    service_scripts.append({
                        'content': [script.get('content', "") for script in normal_scripts], 
                        'type': [script.get('type', 'python') for script in normal_scripts],
                        'service_name': service_name,
                        'is_list': True
                    })
            else:
                logger.debug(f"[Auto@{self.max_workers}] No setup script found for service: {service_name}")
        
        if service_scripts:
            logger.info(f"[Auto@{self.max_workers}] Executing {len(service_scripts)} service-level setup scripts in parallel")
            
            # Prepare scripts for executor's parallel execution
            scripts_for_executor = []
            for script in service_scripts:
                service_config = builds[script['service_name']]
                scripts_for_executor.append({
                    'content': script['content'],
                    'type': script['type'],
                    'config': service_config, 
                    'service_name': script['service_name'],
                    'is_list': script.get('is_list', False)
                })
            
            results = self.executor.parallel(scripts_for_executor)
            # Apply returned configs back to builds to ensure parallel changes persist
            if isinstance(results, dict):
                for svc_name, new_conf in results.items():
                    try:
                        builds[svc_name] = new_conf
                    except Exception as e:
                        logger.error(f"[Auto@{self.max_workers}] Failed to apply setup result for service '{svc_name}': {e}")
            current_config["builds"] = builds

        logger.info(f"[Auto@{self.max_workers}] Setup phase completed")
    
    def modify(self, config: Dict[str, Any]) -> None:
        """
        Execute the modify phase.

        Args:
            config: Full configuration object
            
        Returns:
            Modified configuration
        """
        logger.info(f"[Auto@{self.max_workers}] Starting modify phase")
        
        # Validate modify phase restrictions before execution
        self._validate_modify_restrictions(config)
        
        # Get automation config
        auto_config = config.get('auto', {})
        global_modify = auto_config.pop('modify', None)
        current_config = config
        if global_modify:
            if isinstance(global_modify, str):
                # Single script
                logger.info(f"[Auto@{self.max_workers}] Executing global modify script: {global_modify[:20]}...")
                current_config = self.executor.execute_script(
                    global_modify,
                    'python',
                    current_config
                )
            else:
                # List of scripts - execute serially
                logger.info(f"[Auto@{self.max_workers}] Executing {len(global_modify)} global modify scripts serially")
                for i, script in enumerate(self._normalize_scripts(global_modify)):
                    current_config = self.executor.execute_script(
                        script.get('content', ""),
                        script.get('type', 'python'),
                        current_config
                    )
        else:
            logger.debug(f"[Auto@{self.max_workers}] No global modify script found")
        
        service_scripts = []
        builds = current_config.get('builds', {})
        
        for service_name, build_config in builds.items():
            # Skip services with build: false (templates)
            if not build_config.get('build', True):
                logger.debug(f"[Auto@{self.max_workers}] Skipping modify for service '{service_name}' (build=false)")
                continue
                
            service_auto = build_config.get('auto', {})
            service_modify = service_auto.pop('modify', None)
            
            if service_modify:
                if isinstance(service_modify, str):
                    # Single script
                    service_scripts.append({
                        'content': service_modify,
                        'type': 'python',
                        'service_name': service_name
                    })
                else:
                    normal_scripts = self._normalize_scripts(service_modify)
                    service_scripts.append({
                        'content': [script.get('content', "") for script in normal_scripts], 
                        'type': [script.get('type', 'python') for script in normal_scripts],
                        'service_name': service_name,
                        'is_list': True
                    })
            else:
                logger.debug(f"[Auto@{self.max_workers}] No modify script found for service: {service_name}")
        
        if service_scripts:
            logger.info(f"[Auto@{self.max_workers}] Executing {len(service_scripts)} service-level modify scripts in parallel")
            
            # Prepare scripts for executor's parallel execution
            scripts_for_executor = []
            for script in service_scripts:
                service_config = builds[script['service_name']]
                scripts_for_executor.append({
                    'content': script['content'],
                    'type': script['type'],
                    'config': service_config, 
                    'service_name': script['service_name'],
                    'is_list': script.get('is_list', False)
                })
            
            results = self.executor.parallel(scripts_for_executor)
            # Apply returned configs back to builds to ensure parallel changes persist
            if isinstance(results, dict):
                for svc_name, new_conf in results.items():
                    try:
                        builds[svc_name] = new_conf
                    except Exception as e:
                        logger.error(f"[Auto@{self.max_workers}] Failed to apply modify result for service '{svc_name}': {e}")
            current_config["builds"] = builds

        logger.info(f"[Auto@{self.max_workers}] Modify phase completed")
    
    def restrict(self, config: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Execute the restrict phase.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            List of dictionaries with 'service_name' and 'result' keys from restrict scripts
        """
        logger.info(f"[Auto@{self.max_workers}] Starting restrict phase")
        
        all_scripts = []
        
        # Global restrict scripts
        global_restrict = config.get("auto", {}).get("restrict")
        if global_restrict:
            if isinstance(global_restrict, str):
                all_scripts.append({
                    'content': global_restrict,
                    'type': 'python',
                    'config': config,
                    'service_name': None
                })
            else:
                for script_def in self._normalize_scripts(global_restrict):
                    all_scripts.append({
                        'content': script_def['content'],
                        'type': script_def['type'],
                        'config': config,
                        'service_name': None
                    })
        
        # Service-level restrict scripts
        builds = config.get("builds", {})
        for service_name, service_config in builds.items():
            # Skip services with build: false (templates)
            if not service_config.get('build', True):
                logger.debug(f"[Auto@{self.max_workers}] Skipping restrict for service '{service_name}' (build=false)")
                continue
                
            service_restrict = service_config.get("auto", {}).get("restrict")
            if service_restrict:
                if isinstance(service_restrict, str):
                    all_scripts.append({
                        'content': service_restrict,
                        'type': 'python',
                        'config': service_config,
                        'service_name': service_name
                    })
                else:
                    # List of scripts
                    for script_def in self._normalize_scripts(service_restrict):
                        all_scripts.append({
                            'content': script_def['content'],
                            'type': script_def['type'],
                            'config': service_config,
                            'service_name': service_name
                        })
        
        if all_scripts:
            logger.info(f"[Auto@{self.max_workers}] Executing {len(all_scripts)} restrict scripts in parallel")
            results = self.executor.parallel_res(all_scripts)
        else:
            results = []
        
        logger.info(f"[Auto@{self.max_workers}] Restrict phase completed")
        return results
    
    def _normalize_scripts(self, scripts: List[Union[str, Dict[str, Any]]]) -> List[Dict[str, str]]:
        """
        Normalize script definitions to a consistent format.
        All scripts are now treated as Python code.
        
        Args:
            scripts: List of script definitions (strings or dicts)
            
        Returns:
            List of normalized script definitions with 'content' and 'type'
        """
        normalized = []
        
        for script in scripts:
            if isinstance(script, str):
                # Simple string script - treat as Python
                normalized.append({
                    'content': script,
                    'type': 'python'
                })
            elif isinstance(script, dict):
                # Script definition with explicit type
                content = script.get('content', script.get('script', ''))
                script_type = script.get('type', 'python')  # Default to python
                normalized.append({
                    'content': content,
                    'type': script_type
                })
            else:
                raise UnsupportedFeatureError(f"Invalid script definition: {script}")
        
        return normalized
    
    def _validate_modify_restrictions(self, config: Dict[str, Any]) -> None:
        """
        Validate modify phase restrictions to avoid re-resolution.
        
        Args:
            config: Full configuration object
            
        Raises:
            UnsupportedFeatureError: If restricted fields are found during modify phase
        """
        # Check global level restrictions
        if 'include' in config and config['include'] is not None:
            raise UnsupportedFeatureError(
                "Global 'include' field is not allowed when modify phase is present. "
                "This restriction prevents the need for re-resolution after modification."
            )
        
        # Check service level restrictions
        builds = config.get('builds', {})
        for service_name, build_config in builds.items():
            if 'ref' in build_config and build_config['ref'] is not None:
                raise UnsupportedFeatureError(
                    f"Service '{service_name}' cannot have 'ref' field when modify phase is present. "
                    "This restriction prevents the need for re-resolution after modification."
                )