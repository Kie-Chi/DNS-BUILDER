from fastapi import Depends
from ..io.fs import FileSystem, create_app_fs

from .services.build_service import BuildService
from .services.project_service import ProjectService
from .services.resource_service import ResourceService
from ..exceptions import DNSBuilderError

app_fs : FileSystem | None = None

def register_fs(use_vfs: bool) -> FileSystem:
    global app_fs
    if app_fs is not None:
        return app_fs
    app_fs = create_app_fs(use_vfs)
    return app_fs

def get_fs() -> FileSystem:
    global app_fs
    if app_fs is None:
        raise DNSBuilderError("FileSystem is not registered. Please call register_fs first.")
    return app_fs


def get_build_service(fs: FileSystem = Depends(get_fs)) -> BuildService:
    return BuildService(fs=fs)


def get_project_service(fs: FileSystem = Depends(get_fs)) -> ProjectService:
    return ProjectService(fs=fs)


def get_resource_service(fs: FileSystem = Depends(get_fs)) -> ResourceService:
    return ResourceService(fs=fs)
