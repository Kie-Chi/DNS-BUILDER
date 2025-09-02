from functools import total_ordering
import re

@total_ordering
class Version:
    """
        Class describe version of SoftWare
    """
    # 1:Major, 2:Minor, 3:Patch, 4:Prerelease
    SEMVER_REGEX = re.compile(
        r"^(?P<major>0|[1-9]\d*)\."
        r"(?P<minor>0|[1-9]\d*)\."
        r"(?P<patch>0|[1-9]\d*)"
        r"(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
        r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
        r"(?:\+(?P<build>\S+))?$"
    )

    def __init__(self, version_str: str):
        self.version_str = version_str
        
        match = self.SEMVER_REGEX.match(version_str)
        if not match:
            if '-' in version_str:
                core_part, prerelease_part = version_str.split('-', 1)
                try:
                    test_core = Version(core_part) # raise ValueError if core_part invalid
                except ValueError:
                    raise ValueError(f"Unrecognized Version '{version_str}'")
            else:
                core_part_match = re.match(r"(\d+\.\d+\.\d+)", version_str)
                if core_part_match:
                    core_part = core_part_match.group(1)
                    prerelease_part = version_str[len(core_part):]
                else: 
                     raise ValueError(f"Unrecognized Version '{version_str}'")

            self.core = tuple(map(int, core_part.split('.')))
            self.prerelease = self._parse_prerelease(prerelease_part)
        else:
            parts = match.groupdict()
            self.core = (int(parts['major']), int(parts['minor']), int(parts['patch']))
            self.prerelease = self._parse_prerelease(parts.get('prerelease'))

    def _parse_prerelease(self, prerelease_str):
        if prerelease_str is None:
            return None
        parts = []
        for part in re.split(r'(\d+)', prerelease_str):
            if not part: continue
            if part.isdigit():
                parts.append(int(part))
            else:
                # 'rc.1' or 'p' or just 'a'
                for sub_part in part.split('.'):
                    if sub_part: parts.append(sub_part)
        return tuple(parts)

    def __str__(self):
        return self.version_str

    def __repr__(self):
        return f"Version('{self.version_str}')"

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.core == other.core and self.prerelease == other.prerelease

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        
        if self.core != other.core:
            return self.core < other.core
        
        if self.prerelease is None and other.prerelease is not None:
            return False
        if self.prerelease is not None and other.prerelease is None:
            return True
        
        if self.prerelease is not None:
            return self.prerelease < other.prerelease
        
        return False
    
