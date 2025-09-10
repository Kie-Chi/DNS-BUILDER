from ..utils.path import DNSBPath, is_path_valid
from typing import List, Dict  

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
        if isinstance(volume, str):
            self._init_short()
        elif isinstance(volume, list):
            self._init_list()

    def _init_short(self):
        """
        Initialize volume from short syntax like:
            volumes:
                - source:target:mode
        """
        args, last = self.origin_volume.rsplit(':', 1)
        if last in ['ro', 'rw']:
            src, dst, self.mode = self.origin_volume.rsplit(':', 2)
            self.src = DNSBPath(src)
            self.dst = DNSBPath(dst)
        elif is_path_valid(last):
            self.src = DNSBPath(args)
            self.dst = DNSBPath(last)
            self.mode = None
        else:
            raise BuildError(f"Invalid volume format: {self.origin_volume}, we expect src:dst[:mode]")


    def _init_list(self):
        """
        Initialize volume from list syntax like:
            volumes:
                - source:
                - target:
                ....
        """
        pass