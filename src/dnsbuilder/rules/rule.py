
import re
from .version import Version

class Rule:
    """
        Class Rule used to describe a rule about versions
    """
    
    def __init__(self, rule_str: str):
        """
        - range: [1.0, 2.0], (1.0, 2.0), [1.0, 2.0), (1.0, 2.0]
        - compare: >=1.2.3, <2.0.0
        - equal: 1.5.0
        """
        self.rule_str = rule_str.strip()
        self.check = self._parse_rule()

    def _parse_rule(self):
        """
            parse a rule
        """
        match = re.match(r"^(\[|\()\s*(.+?)\s*,\s*(.+?)\s*(\]|\))$", self.rule_str)
        
        if match:
            start_bracket, start_ver_str, end_ver_str, end_bracket = match.groups()
            
            start_ver = Version(start_ver_str)
            end_ver = Version(end_ver_str)
            
            checks = []
            if start_bracket == '[':
                checks.append(lambda v: start_ver <= v)
            else: # '('
                checks.append(lambda v: start_ver < v)
            
            if end_bracket == ']':
                checks.append(lambda v: v <= end_ver)
            else: # ')'
                checks.append(lambda v: v < end_ver)

            return lambda v: checks[0](v) and checks[1](v)

        op_map = {
            '>=': lambda v, t: v >= t,
            '<=': lambda v, t: v <= t,
            '>': lambda v, t: v > t,
            '<': lambda v, t: v < t,
        }
        for op, func in op_map.items():
            if self.rule_str.startswith(op):
                version_part = self.rule_str[len(op):].strip()
                target_version = Version(version_part)
                return lambda v: func(v, target_version)
                
        target_version = Version(self.rule_str)
        return lambda v: v == target_version

    def __contains__(self, version: Version) -> bool:
        """
            `version in rule`
        """
        if not isinstance(version, Version):
            return False
        return self.check(version)

    def __str__(self):
        return f"{self.rule_str}"

    def __repr__(self):
        return f"Rule('{self.rule_str}')"