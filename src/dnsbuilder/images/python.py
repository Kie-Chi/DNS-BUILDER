from typing import Any, Dict, override
from .image import Image
import logging
logger = logging.getLogger(__name__)

class PythonImage(Image):
    """
        Concrete Image class for Python
    """
    def __init__(self, config: Dict[str, Any]):
        self.pip_deps = []
        super().__init__(config)
    
    @override
    def _load_defaults(self):
        super()._load_defaults()
        if ":" in self.name:
            # ensure the base os is 'python', not 'ubuntu'
            self.os = "python"

    @override
    def _post_init_hook(self):
        """
        Handle Python's specific dependency logic.
        """
        self.dependency = []

        pip_pkg_names = [dep.split("python3-")[-1] for dep in self.util if dep.startswith("python3-")]
        
        self.pip_deps = sorted(list(set(pip_pkg_names)))

        if self.pip_deps:
            # Filter out pip packages from the system utility list
            self.util = [dep for dep in self.util if not dep.startswith("python3-")]
            logger.debug(f"[{self.name}] Processed Python pip dependencies: {self.pip_deps}")

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        """
        Extend base template variables with Python-specific ones.
        """
        base_vars = super()._get_template_vars()
        pip_packages = " ".join(self.pip_deps)
        base_vars['pip_packages'] = f"RUN pip install --no-cache-dir {pip_packages}" if pip_packages else ""
        # Ensure dep_packages is empty for the template
        base_vars['dep_packages'] = ""
        return base_vars

    @override
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure python dependencies from the parent are correctly carried over.
        """
        merged = super().merge(child_config)
        # Re-add the python3- prefixed deps to the 'util' list for accurate merging
        merged['util'].extend([f"python3-{dep}" for dep in self.pip_deps])
        merged['util'] = sorted(list(set(merged['util'])))
        logger.debug(f"[{self.name}] [PythonImage] Fully Merged Result : {merged}")
        return merged