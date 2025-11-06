import tempfile
import os
from typing import Any, Dict, List, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
from ..io.fs import FileSystem
from ..io.path import DNSBPath
from ..exceptions import DefinitionError
logger = logging.getLogger(__name__)


class ScriptExecutor:
    """Executor for Python automation scripts."""
    
    def __init__(self, max_workers: Optional[int] = None, fs: Optional[FileSystem] = None):
        """
        Initialize the script executor.
        
        Args:
            max_workers: Maximum number of worker processes
            fs: File system instance to use. If None, creates default app filesystem
        """
        if max_workers is None:
            max_workers = os.cpu_count() or 1
        self.max_workers = max_workers
        
        if fs is None:
            raise DefinitionError("FileSystem must be provided to ScriptExecutor")
        self.fs = fs
    
    def exec_python(self, script_content: str, config: Dict[str, Any], 
                            service_name: Optional[str] = None) -> Any:
        """
        Execute a Python script with the given configuration.
        
        Args:
            script_content: Python script content
            config: Configuration object to pass to the script
            service_name: Service name (for service-level scripts)
            
        Returns:
            For setup/modify scripts: Modified configuration
            For restrict scripts: The 'result' variable set by the script, or None if not set
        """
        try:
            if self.fs:
                logger.debug(f"[Auto@{self.max_workers}] Executing Python script using temp filesystem")
                import uuid
                script_id = str(uuid.uuid4())[:8]
                temp_script_path = DNSBPath(f"temp://scripts/script_{script_id}.py")
                
                # Write to temp filesystem
                self.fs.write_text(temp_script_path, script_content)
                
                # Prepare the execution environment
                globals_dict = {
                    'config': config,
                    'service_name': service_name,
                    'result': None, 
                    '__name__': '__main__'
                }
                with self.fs.open(temp_script_path, 'r') as f:
                    exec(f.read(), globals_dict)
                if globals_dict.get('result') is None:
                    return globals_dict.get('config', config)
                return globals_dict.get('result', None)
            else:
                logger.debug(f"[Auto@{self.max_workers}] Executing Python script using standard tempfile")
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    f.write(script_content)
                    script_path = f.name
                globals_dict = {
                    'config': config,
                    'service_name': service_name,
                    'result': None,  # Initialize result variable for restrict scripts
                    '__name__': '__main__'
                }
                with open(script_path, 'r') as f:
                    exec(f.read(), globals_dict)
                os.unlink(script_path)
                
                if globals_dict.get('result') is None:
                    return globals_dict.get('config', config)
                return globals_dict.get('result', None)
            
        except Exception as e:
            logger.error(f"[Auto@{self.max_workers}] Error executing Python script: {e}")
            if not self.fs and 'script_path' in locals():
                try:
                    os.unlink(script_path)
                except Exception as e:
                    logger.debug(f"[Auto@{self.max_workers}] Error cleaning up temp file {script_path}: {e}")
                    pass
            raise
    
    def execute_script(self, script_content: str, script_type: str, 
                      config: Dict[str, Any], service_name: Optional[str] = None) -> Any:
        """
        Execute a Python script. All scripts are now treated as Python code.
        
        Args:
            script_content: Python script content
            script_type: Script type (only 'python' is supported now)
            config: Configuration object
            service_name: Service name (for service-level scripts)
            
        Returns:
            For setup/modify scripts: Modified configuration
            For restrict scripts: The 'result' variable set by the script, or None if not set
        """
        if script_type.lower() == 'python':
            return self.exec_python(script_content, config, service_name)
        else:
            logger.warning(f"Script type '{script_type}' is not supported. Treating as Python code.")
            return self.exec_python(script_content, config, service_name)
    
    def parallel(self, scripts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute multiple setup/modify scripts in parallel.
        
        Args:
            scripts: List of script definitions with 'content', 'type', 'config', and optional 'service_name'
                    is_list: Whether the content is a list of scripts to execute serially
            
        Returns:
            None (scripts modify config in-place)
        """
        if not scripts:
            return
        
        # For single script, execute directly
        if len(scripts) == 1:
            script = scripts[0]
            if script.get('is_list', False):
                config = script['config']
                for i, script_content in enumerate(script['content']):
                    logger.debug(f"[Auto@{self.max_workers}] Executing script {i+1}/{len(script['content'])} for service {script.get('service_name', 'global')}")
                    config = self.execute_script(
                        script_content,
                        script['type'][i],
                        config,
                        script.get('service_name')
                    )
                script['config'] = config
            else:
                # Single script, execute directly
                logger.debug(f"[Auto@{self.max_workers}] Executing single script for service {script.get('service_name', 'global')}")
                script['config'] = self.execute_script(
                    script['content'], 
                    script['type'], 
                    script['config'],  # Config is modified in-place
                    script.get('service_name')
                )
            logger.debug(f"[Auto@{self.max_workers}] Script config after execution: {script['config']}")
            return {script.get('service_name', 'global'): script['config']}
        
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_script = {}
            for script in scripts:
                future = executor.submit(
                    self._exec,
                    script,
                    self  # Pass the executor instance
                )
                future_to_script[future] = script
            
            for future in as_completed(future_to_script):
                script = future_to_script[future]
                try:
                    script['config'] = future.result()
                    logger.debug(f"[Auto@{self.max_workers}] Script config after execution: {script['config']}")
                    logger.info(f"[Auto@{self.max_workers}] Script executed successfully for service: {script.get('service_name', 'global')}")
                except Exception as e:
                    logger.error(f"[Auto@{self.max_workers}] Script execution failed for service {script.get('service_name', 'global')}: {e}")
                    raise
            return {script.get('service_name', 'global'): script['config'] for script in scripts}
    
    def parallel_res(self, scripts: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Execute multiple restrict scripts in parallel and return validation results with service names.
        
        Args:
            scripts: List of script definitions with 'content', 'type', 'config', and 'service_name'
            
        Returns:
            List of dictionaries with 'service_name' and 'result' keys
        """
        if not scripts:
            return []
        
        if len(scripts) == 1:
            script = scripts[0]
            result = self.execute_script(
                script['content'], 
                script['type'], 
                script['config'],
                script.get('service_name')
            )
            logger.debug(f"[Auto@{self.max_workers}] Script result after execution: {result}")
            return [{
                f"{script.get('service_name', 'global')}": str(result) if result is not None else "PASS"
            }]
        
        # For multiple scripts, use parallel execution
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self._exec, script, self) for script in scripts]
            results = []
            for i, future in enumerate(futures):
                script = scripts[i]
                result = future.result()
                logger.debug(f"[Auto@{self.max_workers}] Script result after execution: {result}")
                results.append({
                    f"{script.get('service_name', 'global')}": str(result) if result is not None else "PASS"
                })
        
        return results
    
    @staticmethod
    def _exec(script: Dict[str, Any], executor: Optional['ScriptExecutor'] = None) -> Any:
        """
        Worker function for parallel script execution.
        
        Args:
            script: Script dictionary with 'content', 'type', 'config', and optional 'service_name'
                   is_list: Whether the content is a list of scripts to execute serially
            executor: ScriptExecutor instance to use (if None, creates a new one)
            
        Returns:
            For setup/modify scripts: Modified configuration
            For restrict scripts: The 'result' variable set by the script, or None if not set
        """
        if executor is None:
            executor = ScriptExecutor()
        
        if script.get('is_list', False):
            # Execute list of scripts serially within this service
            config = script['config']
            for i, script_content in enumerate(script['content']):
                logger.debug(f"[Auto@{executor.max_workers}] Executing script {i+1}/{len(script['content'])} for service {script.get('service_name', 'global')}")
                config = executor.execute_script(
                    script_content,
                    script['type'][i],
                    config,
                    script.get('service_name')
                )
            return config
        else:
            # Single script
            return executor.execute_script(
                script['content'], 
                script['type'], 
                script['config'], 
                script.get('service_name')
            )
    
    # Alias
    _execute_script_worker = _exec