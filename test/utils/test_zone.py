# tests/test_zone.py

import pytest
from dnsbuilder.utils.zone import Zone, ZoneName


class TestZone:
    """Unit tests for the Zone class."""

    @pytest.mark.parametrize(
        "name, expected_parts, expected_fqdn, expected_label",
        [
            # Standard domain names
            ("example.com", ("example", "com"), "example.com.", "example.com"),
            ("example.com.", ("example", "com"), "example.com.", "example.com"),
            ("www.example.com", ("www", "example", "com"), "www.example.com.", "www.example.com"),
            ("www.example.com.", ("www", "example", "com"), "www.example.com.", "www.example.com"),
            # Root zone variants
            (".", (), ".", "root"),
            ("root", (), ".", "root"),
            ("", (), ".", "root"),
            (".....", (), ".", "root"),
            # TLD
            ("com", ("com",), "com.", "com"),
            ("com.", ("com",), "com.", "com"),
            # Multi-level
            ("a.b.c.example.com", ("a", "b", "c", "example", "com"), "a.b.c.example.com.", "a.b.c.example.com"),
            # With spaces (should be trimmed)
            ("  example.com  ", ("example", "com"), "example.com.", "example.com"),
            ("  .  ", (), ".", "root"),
        ],
    )
    def test_initialization(self, name, expected_parts, expected_fqdn, expected_label):
        """Tests that Zone correctly parses various zone name formats."""
        zone = Zone(name)
        assert zone.parts == expected_parts
        assert zone.fqdn == expected_fqdn
        assert zone.label == expected_label

    def test_parts_property(self):
        """Test that parts is stored correctly."""
        assert Zone("www.example.com").parts == ("www", "example", "com")
        assert Zone("example.com").parts == ("example", "com")
        assert Zone("com").parts == ("com",)
        assert Zone(".").parts == ()

    def test_is_root(self):
        """Test is_root property."""
        assert Zone(".").is_root is True
        assert Zone("root").is_root is True
        assert Zone("").is_root is True
        assert Zone("example.com").is_root is False
        assert Zone("com").is_root is False

    def test_filename(self):
        """Test filename property for zone file naming."""
        assert Zone("example.com").filename == "db.example.com"
        assert Zone(".").filename == "db.root"
        assert Zone("www.example.com").filename == "db.www.example.com"

    @pytest.mark.parametrize(
        "name, expected_name",
        [
            ("www.example.com", "www"),
            ("example.com", "example"),
            ("com", "com"),
            (".", ""),
            ("root", ""),
            ("a.b.c", "a"),
        ],
    )
    def test_name_property(self, name, expected_name):
        """Test name property returns the leftmost label."""
        zone = Zone(name)
        assert zone.name == expected_name

    @pytest.mark.parametrize(
        "name, expected_parent_parts",
        [
            ("www.example.com", ("example", "com")),
            ("example.com", ("com",)),
            ("a.b.c.example.com", ("b", "c", "example", "com")),
            ("com", ()),
        ],
    )
    def test_parent_zone(self, name, expected_parent_parts):
        """Test parent property returns correct parent zone."""
        zone = Zone(name)
        parent = zone.parent
        assert parent is not None
        assert parent.parts == expected_parent_parts

    def test_parent_of_root(self):
        """Test that root zone has no parent."""
        zone = Zone(".")
        assert zone.parent is None
        assert Zone("root").parent is None
        assert Zone("").parent is None

    @pytest.mark.parametrize(
        "zone_name, subdomain, expected_parts",
        [
            ("example.com", "www", ("www", "example", "com")),
            ("example.com", "api", ("api", "example", "com")),
            (".", "com", ("com",)),
            (".", "example", ("example",)),
            ("example.com", "www.api", ("www", "api", "example", "com")),
            # With trailing dot in subdomain (should be stripped)
            ("example.com", "www.", ("www", "example", "com")),
            # Empty subdomain (should return same zone)
            ("example.com", "", ("example", "com")),
            ("example.com", "  ", ("example", "com")),
        ],
    )
    def test_join_method(self, zone_name, subdomain, expected_parts):
        """Test join method for creating subdomains."""
        zone = Zone(zone_name)
        result = zone.join(subdomain)
        assert result.parts == expected_parts

    @pytest.mark.parametrize(
        "zone_name, subdomain, expected_parts",
        [
            ("example.com", "www", ("www", "example", "com")),
            ("example.com", "api", ("api", "example", "com")),
            (".", "com", ("com",)),
            ("example.com", "www.api", ("www", "api", "example", "com")),
        ],
    )
    def test_truediv_operator(self, zone_name, subdomain, expected_parts):
        """Test / operator for creating subdomains (like pathlib.Path)."""
        zone = Zone(zone_name)
        result = zone / subdomain
        assert isinstance(result, Zone)
        assert result.parts == expected_parts

    def test_truediv_chaining(self):
        """Test chaining / operators."""
        zone = Zone("example.com")
        result = zone / "www" / "api"
        assert result.parts == ("api", "www", "example", "com")

        # Alternative: start from root
        root = Zone(".")
        result = root / "com" / "example" / "www"
        assert result.parts == ("www", "example", "com")

    def test_attribute_access_for_subdomains(self):
        """Test attribute access for creating subdomains."""
        zone = Zone("example.com")
        assert zone.www.parts == ("www", "example", "com")
        assert zone.api.parts == ("api", "example", "com")

    def test_attribute_access_chaining(self):
        """Test chaining attribute access for multi-level subdomains."""
        zone = Zone("example.com")
        assert zone.www.api.parts == ("api", "www", "example", "com")

    def test_from_parts_classmethod(self):
        """Test creating Zone from parts tuple."""
        zone = Zone.from_parts(("www", "example", "com"))
        assert zone.parts == ("www", "example", "com")
        assert zone.fqdn == "www.example.com."

        # Empty parts = root
        root = Zone.from_parts(())
        assert root.is_root is True
        assert root.fqdn == "."

    def test_attribute_access_with_hyphen(self):
        """Test attribute access with hyphenated labels (valid DNS labels)."""
        zone = Zone("example.com")
        # Direct attribute access with hyphen doesn't work in Python,
        # but we can test the join method
        result = zone.join("my-api")
        assert result.parts == ("my-api", "example", "com")

    def test_attribute_access_invalid_label(self):
        """Test that invalid DNS labels raise AttributeError."""
        zone = Zone("example.com")
        with pytest.raises(AttributeError, match="Invalid DNS label"):
            _ = zone.invalid_label  # underscore is invalid

    def test_attribute_access_empty(self):
        """Test that empty subdomain raises AttributeError."""
        zone = Zone("example.com")
        # Accessing attribute would be syntax error, so we test via getattr
        # But empty string in __getattr__ is caught by the empty check
        with pytest.raises(AttributeError):
            getattr(zone, "")

    def test_str_representation(self):
        """Test string representation returns FQDN."""
        zone = Zone("example.com")
        assert str(zone) == "example.com."
        assert str(Zone(".")) == "."

    def test_repr_representation(self):
        """Test repr shows parts."""
        zone = Zone("example.com")
        assert repr(zone) == "Zone(parts=('example', 'com'))"
        assert repr(Zone(".")) == "Zone(parts=())"

    def test_equality_with_zone(self):
        """Test equality comparison between Zone objects."""
        zone1 = Zone("example.com")
        zone2 = Zone("example.com.")
        zone3 = Zone("www.example.com")
        assert zone1 == zone2
        assert zone1 != zone3

    def test_equality_with_string(self):
        """Test equality comparison with string."""
        zone = Zone("example.com")
        assert zone == "example.com"
        assert zone == "example.com."
        assert zone != "www.example.com"

    def test_equality_with_other_types(self):
        """Test equality with non-Zone, non-string types returns False."""
        zone = Zone("example.com")
        assert zone != 123
        assert zone != None
        assert zone != ["example.com"]

    def test_hash_consistency(self):
        """Test that equal Zone objects have same hash."""
        zone1 = Zone("example.com")
        zone2 = Zone("example.com.")
        assert hash(zone1) == hash(zone2)

        # Can be used in sets and dicts
        zone_set = {zone1, zone2, Zone("www.example.com")}
        assert len(zone_set) == 2  # zone1 and zone2 are equal

        zone_dict = {zone1: "value"}
        assert zone_dict[zone2] == "value"

    def test_frozen_dataclass(self):
        """Test that Zone is immutable (frozen dataclass)."""
        zone = Zone("example.com")
        with pytest.raises(Exception):  # FrozenInstanceError
            zone.parts = ("modified", "com")

    def test_len_method(self):
        """Test __len__ returns number of parts."""
        assert len(Zone("www.example.com")) == 3
        assert len(Zone("example.com")) == 2
        assert len(Zone("com")) == 1
        assert len(Zone(".")) == 0

    def test_getitem_method(self):
        """Test __getitem__ for accessing parts."""
        zone = Zone("www.example.com")
        assert zone[0] == "www"
        assert zone[1] == "example"
        assert zone[2] == "com"
        assert zone[-1] == "com"
        assert zone[1:3] == ("example", "com")

    def test_parent_chain(self):
        """Test traversing up the parent chain."""
        zone = Zone("api.www.example.com")

        # api.www.example.com -> www.example.com
        assert zone.parent.parts == ("www", "example", "com")

        # www.example.com -> example.com
        assert zone.parent.parent.parts == ("example", "com")

        # example.com -> com. 
        assert zone.parent.parent.parent.parts == ("com", )

        # com -> root
        assert zone.parent.parent.parent.parent.parts == ()
        
        # root -> None
        assert zone.parent.parent.parent.parent.parent is None

    def test_roundtrip(self):
        """Test that fqdn -> Zone -> fqdn is identity."""
        original = "www.example.com."
        zone = Zone(original)
        assert zone.fqdn == original

        # Same with label -> Zone -> fqdn
        zone = Zone("www.example.com")
        assert zone.fqdn == "www.example.com."

    def test_backward_compatibility_alias(self):
        """Test that ZoneName is an alias for Zone."""
        assert ZoneName is Zone
        zone = ZoneName("example.com")
        assert isinstance(zone, Zone)
        assert zone.parts == ("example", "com")

    @pytest.mark.parametrize(
        "zone_name, parent_name, expected",
        [
            # Direct subdomain
            ("www.example.com", "example.com", True),
            # Multi-level subdomain
            ("api.www.example.com", "example.com", True),
            ("api.www.example.com", "www.example.com", True),
            # Same zone - not a subdomain
            ("example.com", "example.com", False),
            # Different domain - not a subdomain
            ("other.com", "example.com", False),
            ("www.other.com", "example.com", False),
            # Root is parent of all non-root
            ("example.com", ".", True),
            ("www.example.com", ".", True),
            # Root is not subdomain of anything
            (".", "example.com", False),
            (".", ".", False),
            # TLD is subdomain of root
            ("com", ".", True),
        ],
    )
    def test_is_subdomain_of(self, zone_name, parent_name, expected):
        """Test is_subdomain_of method."""
        zone = Zone(zone_name)
        assert zone.is_subdomain_of(parent_name) == expected
        # Also test with Zone object
        assert zone.is_subdomain_of(Zone(parent_name)) == expected

    @pytest.mark.parametrize(
        "parent_name, zone_name, expected",
        [
            # Direct parent
            ("example.com", "www.example.com", True),
            # Multi-level parent
            ("example.com", "api.www.example.com", True),
            ("www.example.com", "api.www.example.com", True),
            # Same zone - not a parent
            ("example.com", "example.com", False),
            # Different domain - not a parent
            ("example.com", "other.com", False),
            ("example.com", "www.other.com", False),
            # Root is parent of all non-root
            (".", "example.com", True),
            (".", "www.example.com", True),
            # Non-root is not parent of root
            ("example.com", ".", False),
            # TLD parent
            (".", "com", True),
        ],
    )
    def test_is_parent_of(self, parent_name, zone_name, expected):
        """Test is_parent_of method."""
        zone = Zone(parent_name)
        assert zone.is_parent_of(zone_name) == expected
        # Also test with Zone object
        assert zone.is_parent_of(Zone(zone_name)) == expected

    def test_is_subdomain_of_symmetric(self):
        """Test that is_subdomain_of and is_parent_of are symmetric."""
        parent = Zone("example.com")
        child = Zone("www.example.com")

        assert child.is_subdomain_of(parent) is True
        assert parent.is_parent_of(child) is True
        assert parent.is_subdomain_of(child) is False
        assert child.is_parent_of(parent) is False


if __name__ == "__main__":
    pytest.main()