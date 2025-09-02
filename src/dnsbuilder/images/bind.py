from typing import Any, Dict, override
from .image import Image
import logging
logger = logging.getLogger(__name__)

class BindImage(Image):
    """
        Concrete Image class for BIND
    """

    def __init__(self, config: Dict[str, Any]):
        self.py3_deps = [] # will init in hook
        super().__init__(config)

    @override
    def _post_init_hook(self):
        """
        Handle BIND's specific python3 dependency logic after base setup.
        """
        py3_pkg_names = [dep.split("python3-")[-1] for dep in self.dependency if "python3-" in dep]
        
        if "pip" in py3_pkg_names:
            py3_pkg_names.remove("pip")
        
        self.py3_deps = sorted(list(set(py3_pkg_names)))

        if self.py3_deps:
            self.dependency = [dep for dep in self.dependency if "python3-" not in dep]
            self.dependency.extend(["python3", "python3-pip"])
            logger.debug(f"[{self.name}] Processed Python dependencies: {self.py3_deps}")

    @override
    def _get_template_vars(self) -> Dict[str, Any]:
        """
        Extend base template variables with BIND-specific ones.
        """
        base_vars = super()._get_template_vars()
        py3_packages = " ".join(self.py3_deps)
        base_vars['py3_packages'] = f"RUN pip3 install {py3_packages}" if py3_packages else ""
        return base_vars

    @override
    def merge(self, child_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure python3 dependencies from the parent are correctly carried over.
        """
        merged = super().merge(child_config)
        # Re-add the python3- prefixed deps for accurate merging with child deps
        merged['dependency'].extend([f"python3-{dep}" for dep in self.py3_deps])
        merged['dependency'] = sorted(list(set(merged['dependency'])))
        logger.debug(f"[{self.name}] [BindImage] Fully Merged Result : {merged}")
        return merged