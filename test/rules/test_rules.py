import pytest
from dnsbuilder.rules.rule import Rule
from dnsbuilder.rules.version import Version

@pytest.fixture
def versions_to_test():
    """Provides a standard set of versions for testing rules against."""
    return [
        Version("0.9.0"),
        Version("1.0.0-alpha"),
        Version("1.0.0-rc1"),
        Version("1.0.0"),
        Version("1.5.0"),
        Version("1.9.9"),
        Version("2.0.0-alpha"),
        Version("2.0.0"),
        Version("2.0.1"),
    ]

class TestRule:
    """Comprehensive tests for the Rule class in dnsbuilder.rules.rule."""

    @pytest.mark.parametrize("rule_str, expected_true_versions", [
        ("[1.0.0, 2.0.0]", ["1.0.0", "1.5.0", "1.9.9", "2.0.0", "2.0.0-alpha"]),
        ("(1.0.0, 2.0.0)", ["1.5.0", "1.9.9", "2.0.0-alpha"]),
        ("[1.0.0, 2.0.0)", ["1.0.0", "1.5.0", "1.9.9", "2.0.0-alpha"]),
        ("(1.0.0, 2.0.0]", ["1.5.0", "1.9.9", "2.0.0-alpha", "2.0.0"]),
        ("[1.0.0-rc1, 2.0.0-alpha]", ["1.0.0-rc1", "1.0.0", "1.5.0", "1.9.9", "2.0.0-alpha"]),
    ])
    def test_range_rules(self, rule_str, expected_true_versions, versions_to_test):
        """Test various range rules like [a, b], (a, b), etc."""
        rule = Rule(rule_str)
        for version in versions_to_test:
            should_be_true = version.version_str in expected_true_versions
            assert (version in rule) is should_be_true, \
                f"Version {version} in rule '{rule}' should be {should_be_true}"

    @pytest.mark.parametrize("rule_str, expected_true_versions", [
        (">=1.5.0", ["1.5.0", "1.9.9", "2.0.0-alpha", "2.0.0", "2.0.1"]),
        (">1.5.0", ["1.9.9", "2.0.0-alpha", "2.0.0", "2.0.1"]),
        ("<=1.5.0", ["0.9.0", "1.0.0-alpha", "1.0.0-rc1", "1.0.0", "1.5.0"]),
        ("<1.5.0", ["0.9.0", "1.0.0-alpha", "1.0.0-rc1", "1.0.0"]),
        (">=2.0.0-alpha", ["2.0.0-alpha", "2.0.0", "2.0.1"]),
    ])
    def test_comparison_rules(self, rule_str, expected_true_versions, versions_to_test):
        """Test comparison rules like >=, <, etc."""
        rule = Rule(rule_str)
        for version in versions_to_test:
            should_be_true = version.version_str in expected_true_versions
            assert (version in rule) is should_be_true, \
                f"Version {version} in rule '{rule}' should be {should_be_true}"
    
    def test_exact_match_rule(self, versions_to_test):
        """Test rules that specify an exact version."""
        rule_str = "1.5.0"
        expected_true_versions = ["1.5.0"]
        rule = Rule(rule_str)
        for version in versions_to_test:
            should_be_true = version.version_str in expected_true_versions
            assert (version in rule) is should_be_true, \
                f"Version {version} in rule '{rule}' should be {should_be_true}"

    def test_exact_match_prerelease(self, versions_to_test):
        """Test exact match for a pre-release version."""
        rule_str = "1.0.0-rc1"
        expected_true_versions = ["1.0.0-rc1"]
        rule = Rule(rule_str)
        for version in versions_to_test:
            should_be_true = version.version_str in expected_true_versions
            assert (version in rule) is should_be_true, \
                f"Version {version} in rule '{rule}' should be {should_be_true}"

    def test_contains_non_version_object(self):
        """'in' operator should return False for non-Version objects."""
        rule = Rule(">=1.0.0")
        assert ("1.2.3" in rule) is False
        assert (123 in rule) is False
        assert (None in rule) is False
        
    @pytest.mark.parametrize("invalid_rule_str", [
        "",           # Empty string
        "1.0.0",      # Your Rule parser supports this, but let's imagine it's an invalid rule context
        "[1.0.0]",    # Incomplete range
        "==1.0.0",    # Unsupported operator
        ">= 1.0.0, < 2.0.0", # Multiple rules in one string
        "garbage",    # Not a valid version or rule format
    ])
    def test_invalid_rule_string_parsing(self, invalid_rule_str):
        """
        Test that invalid rule strings raise an exception.
        """
        invalid_cases = [
            "[1.0.0]",
            "==1.0.0",
            "[1.0, 2.0, 3.0]", # too many items
            "<>1.0.0"
        ]
        for case in invalid_cases:
            with pytest.raises(Exception):
                Rule(case)