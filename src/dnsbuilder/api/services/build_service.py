import hashlib
import threading
import time
import logging
import asyncio
from typing import Dict, List, Optional
from ...builder.build import Builder
from ...config import Config
from ...io.path import DNSBPath
from ...io.fs import FileSystem
from .log_handle import UILogHandler
from ..wsm import manager

builds: Dict[str, Dict] = {}

def run_build(project_name: str, build_id: str, debug: bool, generate_graph: bool):
    builds[build_id]["status"] = "running"
    asyncio.run(manager.broadcast(f"Build {build_id} started."))
    logger = logging.getLogger(f"build.{build_id}")
    handler = UILogHandler(build_id, builds[build_id]["logs"])
    logger.addHandler(handler)
    try:
        # This is a simplification. In a real app, you'd get the config path from the project service.
        config_path = f".dnsb_cache/workspaces/{project_name}/dnsbuilder.yml"
        config = Config(config_path)
        builder = Builder(config, graph_output=f"output/{project_name}/graph.dot" if generate_graph else None)
        builder.run()
        builds[build_id]["status"] = "completed"
        asyncio.run(manager.broadcast(f"Build {build_id} completed."))
    except Exception as e:
        logger.error(f"Build failed: {e}")
        builds[build_id]["status"] = "failed"
        asyncio.run(manager.broadcast(f"Build {build_id} failed."))
    finally:
        builds[build_id]["end_time"] = time.time()
        logger.removeHandler(handler)

class BuildService:
    def __init__(self, fs: FileSystem):
        self.fs: FileSystem = fs

    def start_build(self, project_name: str, debug: bool, generate_graph: bool) -> str:
        # Generate semantic build ID based on project name and timestamp
        timestamp = str(time.time())
        build_id = hashlib.sha256(f"{project_name}:{timestamp}".encode()).hexdigest()[:32]
        builds[build_id] = {
            "status": "started",
            "start_time": time.time(),
            "end_time": None,
            "logs": [],
            "project_name": project_name  # 添加项目名称到构建状态中
        }
        thread = threading.Thread(target=run_build, args=(project_name, build_id, debug, generate_graph))
        thread.start()
        return build_id

    def get_build_status(self, build_id: str) -> Optional[Dict]:
        return builds.get(build_id)

    def get_build_logs(self, build_id: str, since: int = 0) -> Optional[Dict]:
        build = builds.get(build_id)
        if not build:
            return None
        logs = build["logs"][since:]
        return {"logs": logs, "last_index": since + len(logs)}

    def get_build_artifacts(self, project_name: str) -> List[str]:
        output_dir = DNSBPath("output") / project_name
        if not self.fs.exists(output_dir):
            return []
        artifacts = []
        for item in self.fs.rglob(output_dir, "**"):
            if self.fs.is_file(item):
                artifacts.append(str(item.relative_to(self.fs.absolute(output_dir))))
        return artifacts

    def get_build_artifact_content(self, build_id: str, file_path: str) -> Optional[str]:
        """
        Get Build ID Artifact Content
        
        Args:
            build_id: build id
            file_path: relative path like "recursor/Dockerfile"
            
        Returns:
            String Contents of the Artifact
        """
        build = builds.get(build_id)
        if not build:
            return None
            
        project_name = build.get("project_name")
        if not project_name:
            return None
            
        output_dir = DNSBPath("output") / project_name
        full_file_path = output_dir / file_path
        
        if self.fs.exists(full_file_path) and not self.fs.is_dir(full_file_path):
            try:
                return self.fs.read_text(full_file_path)
            except Exception:
                return None
        return None