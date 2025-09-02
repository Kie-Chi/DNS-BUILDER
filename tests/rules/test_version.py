import pytest
from dnsbuilder.rules.version import Version

class TestVersion:
    """Tests for the Version class in dnsbuilder.rules.version."""

    @pytest.mark.parametrize("v1_str, v2_str, expected", [
        ("1.0.0", "1.0.0", True),
        ("1.0.0", "1.0.1", False),
        ("1.2.3", "1.2.3", True),
        ("1.0.0rc1", "1.0.0", False),
        ("1.0.0-rc1", "1.0.0rc1", True)
    ])
    def test_equality(self, v1_str, v2_str, expected):
        """Test the equality (==) of two Version objects."""
        assert (Version(v1_str) == Version(v2_str)) is expected

    @pytest.mark.parametrize("v1_str, v2_str, expected", [
        ("1.0.1", "1.0.0", True),
        ("1.1.0", "1.0.10", True),
        ("2.0.0", "1.9.9", True),
        ("1.0.0", "1.0.0", False),
        ("1.0.0", "1.0.1", False),
        ("1.0.0-rc1", "1.0.0", False),
        ("1.0.1-rc2", "1.0.0", True),
    ])
    def test_greater_than(self, v1_str, v2_str, expected):
        """Test the greater than (>) comparison."""
        assert (Version(v1_str) > Version(v2_str)) is expected

    @pytest.mark.parametrize("lesser_str, greater_str", [
        ("1.0.0", "1.0.1"),   # Patch increment
        ("1.0.9", "1.0.10"), # Patch increment with two digits
        ("1.0.0", "1.1.0"),   # Minor increment
        ("1.9.0", "1.10.0"),  # Minor increment with two digits
        ("1.0.0", "2.0.0"),   # Major increment
    ])
    def test_core_version_ordering(self, lesser_str, greater_str):
        """Test ordering of major, minor, and patch numbers."""
        lesser = Version(lesser_str)
        greater = Version(greater_str)
        assert lesser < greater
        assert greater > lesser
        assert lesser != greater

    def test_prerelease_is_lower_than_release(self):
        """A version with a pre-release tag is always lower than the final release."""
        assert Version("1.0.0-alpha") < Version("1.0.0")
        assert Version("1.0.0-rc.1") < Version("1.0.0")
        assert Version("2.3.1-beta") < Version("2.3.1")

    @pytest.mark.parametrize("lesser_str, greater_str", [
        ("1.0.0-a", "1.0.0-b"),
        ("1.0.0-alpha", "1.0.0-beta"),
        ("1.0.0-beta", "1.0.0-rc"),
        ("1.0.0-rc", "1.0.0-release"), # 'release' is just another identifier
    ])
    def test_prerelease_alphabetical_ordering(self, lesser_str, greater_str):
        """Test alphabetical ordering of string pre-release tags."""
        assert Version(lesser_str) < Version(greater_str)

    @pytest.mark.parametrize("lesser_str, greater_str", [
        ("1.0.0-rc.1", "1.0.0-rc.2"),
        ("1.0.0-alpha.9", "1.0.0-alpha.10"),
    ])
    def test_prerelease_numeric_ordering(self, lesser_str, greater_str):
        """Test numeric ordering of pre-release tags."""
        assert Version(lesser_str) < Version(greater_str)


    # will support hex later
    # def test_prerelease_numeric_has_lower_precedence_than_string(self):
        """Numeric identifiers have lower precedence than non-numeric ones."""

        # assert Version("1.0.0-alpha.1") < Version("1.0.0-alpha.a")
        # assert Version("1.0.0-9") < Version("1.0.0-a")
        
    @pytest.mark.parametrize("lesser_str, greater_str", [
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.1.2"),
        ("1.0.0-beta", "1.0.0-beta.2"),
        ("1.0.0-beta.2", "1.0.0-beta.11"),
    ])
    def test_prerelease_field_count_ordering(self, lesser_str, greater_str):
        """A larger set of pre-release fields has a higher precedence."""
        assert Version(lesser_str) < Version(greater_str)

    @pytest.mark.parametrize("lesser_str, greater_str", [
        ("9.11.0-P1", "9.11.0-P2"),
        ("9.18.18-S1", "9.18.18"), 
        ("1.9.0rc1", "1.9.0"),
        ("1.9.0rc1", "1.9.0rc2"),
        ("1.0.0-alpha", "1.0.0-alpha.1"),
        ("1.0.0-alpha.1", "1.0.0-alpha.2"),
        ("1.0.0-alpha.beta", "1.0.0-beta"),
        ("1.0.0-beta", "1.0.0-beta.2"),
        ("1.0.0-beta.2", "1.0.0-beta.11"),
        ("1.0.0-beta.11", "1.0.0-rc.1"),
        ("1.0.0-rc.1", "1.0.0"),
    ])
    def test_complex_and_real_world_examples(self, lesser_str, greater_str):
        """Test a sequence of complex and real-world pre-release versions."""
        assert Version(lesser_str) < Version(greater_str)

    @pytest.mark.parametrize("version_str, expected_core, expected_prerelease", [
        ("1.2.3", (1, 2, 3), None),
        ("9.18.18", (9, 18, 18), None),
        ("1.9.0rc1", (1, 9, 0), ('rc', 1)),
        ("9.11.0-P1", (9, 11, 0), ('P', 1)),
        ("1.0.0-alpha.beta", (1, 0, 0), ('alpha', 'beta')),
        ("1.0.0-alpha.1", (1, 0, 0), ('alpha', 1)),
    ])
    def test_version_parsing(self, version_str, expected_core, expected_prerelease):
        """Verify that the parser correctly separates core and pre-release parts."""
        v = Version(version_str)
        assert v.core == expected_core
        assert v.prerelease == expected_prerelease

    @pytest.mark.parametrize("invalid_str", [
        "1",
        "1.2",
        "a.b.c",
        "invalid-version",
    ])
    def test_invalid_version_strings(self, invalid_str):
        """Test that invalid version strings correctly raise a ValueError."""
        with pytest.raises(ValueError, match=f"Unrecognized Version '{invalid_str}'"):
             Version(invalid_str)