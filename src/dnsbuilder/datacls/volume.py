from typing import List, Dict, NamedTuple

from .. import constants
from ..io.path import DNSBPath, is_path_valid
from ..exceptions import VolumeError

class Pair(NamedTuple):
    src: DNSBPath
    dst: str

"""
    Class Volume to resolve volumes like src:dst:mode
    We will support list-like volumes config later like:
        volumes:
            - source:
            - target:
            ....
"""
class Volume:
    def __init__(self, volume: List[Dict] | str):
        self.origin_volume = volume
        self.is_origin = False
        self.is_required = False
        if isinstance(volume, str):
            self._init_short()
        elif isinstance(volume, list):
            self._init_list()
    
    def __post_init__(self):
        if not self.src.exists():
            raise VolumeError(f"Source volume {self.src} does not exist")
        if self.mode not in ['ro', 'rw']:
            raise VolumeError(f"Invalid volume mode {self.mode}, we expect ro or rw")

    def __check_required(self, path: str) -> bool:
        if path.startswith(constants.PLACEHOLDER["REQUIRED"]):
            return True
        return False

    def _init_short(self):
        """
        Initialize volume from short syntax like:
            volumes:
                - source:target:mode
        """
        if self.origin_volume.startswith(constants.PLACEHOLDER["ORIGIN"]):
            self.is_origin = True
            self.origin_volume = self.origin_volume[len(constants.PLACEHOLDER["ORIGIN"]):]
        args, last = self.origin_volume.rsplit(':', 1)
        if last in ['ro', 'rw']:
            src, dst, self.mode = self.origin_volume.rsplit(':', 2)
            if self.__check_required(src):
                self.is_required = True
                self.src = None
            else:
                self.src = DNSBPath(src, is_origin=self.is_origin)
            self.dst = DNSBPath(dst)
        elif is_path_valid(last):
            if self.__check_required(args):
                self.is_required = True
                self.src = None
            else:
                self.src = DNSBPath(args, is_origin=self.is_origin)
            self.dst = DNSBPath(last)
            self.mode = None
        else:
            raise VolumeError(f"Invalid volume format: {self.origin_volume}, we expect src:dst[:mode]")


    def _init_list(self):
        """
        Initialize volume from list syntax like:
            volumes:
                - source:
                - target:
                ....
        """
        pass

    def __str__(self):
        return self.origin_volume.__str__()
