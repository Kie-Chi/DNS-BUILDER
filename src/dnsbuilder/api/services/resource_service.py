from typing import List, Dict
import yaml
import json

from ...io.fs import FileSystem
from ...io.path import DNSBPath

class ResourceService:
    def __init__(self, fs: FileSystem, resources_path: DNSBPath = DNSBPath("resource:/")):
        self.fs = fs
        self.resources_path = resources_path

    def get_includes(self) -> List[Dict[str, str]]:
        includes_path = self.resources_path / "includes"
        templates = []
        if self.fs.exists(includes_path) and self.fs.is_dir(includes_path):
            for file_path in self.fs.listdir(includes_path):
                if file_path.name.endswith(".yml"):
                    content = self.fs.read_text(file_path)
                    try:
                        data = yaml.safe_load(content)
                        templates.append({
                            "name": file_path.name,
                            "description": data.get("description", "")
                        })
                    except yaml.YAMLError:
                        continue
        return templates

    def get_software(self) -> List[str]:
        software_path = self.resources_path / "images" / "templates"
        software = []
        if self.fs.exists(software_path) and self.fs.is_dir(software_path):
            for item in self.fs.listdir(software_path):
                if not item.name.startswith("__"):
                    software.append(item.name)
        return software

    def get_software_rules(self, software_name: str) -> List[Dict[str, str]]:
        rules_path = self.resources_path / "images" / "rules" / software_name
        rules = []
        if self.fs.exists(rules_path):
            content = self.fs.read_text(rules_path)
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    for version, deps in data.items():
                        rules.append({
                            "version": version,
                            "dependency": deps
                        })
            except json.JSONDecodeError:
                pass
        return rules