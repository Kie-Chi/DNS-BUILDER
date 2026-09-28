import pytest

from dnsbuilder.bases.behaviors import PdnsAuthMasterBehavior, PdnsRecursorMasterBehavior
from dnsbuilder.config import ConfigModel
from dnsbuilder.registry import (
    behavior_registry,
    image_registry,
    includer_registry,
    initialize_registries,
    section_registry,
)
from dnsbuilder.constants import normalize_software_name


@pytest.fixture(autouse=True)
def _discover_builtin_registries():
    initialize_registries(load_plugins=False)


def test_powerdns_authoritative_has_independent_registrations():
    assert image_registry.image("pdns_auth").__name__ == "PdnsAuthImage"
    assert behavior_registry.behavior("pdns_auth", "master") is PdnsAuthMasterBehavior
    assert section_registry.section("pdns_auth").__name__ == "PdnsAuthSection"
    assert includer_registry.includer("pdns_auth").__name__ == "PdnsAuthIncluder"

    # Authoritative and Recursor must not share the behavior/section/includer
    # registry key even though both are PowerDNS components.
    assert behavior_registry.behavior("pdns_auth", "master") is not PdnsRecursorMasterBehavior
    assert behavior_registry.behavior("pdns_recursor", "master") is PdnsRecursorMasterBehavior


def test_pdns_recur_is_only_a_recursor_alias():
    assert normalize_software_name("pdns_recur") == "pdns_recursor"
    assert normalize_software_name("pdns-recur") == "pdns_recursor"
    assert image_registry.image("pdns_recur").__name__ == "PdnsRecursorImage"
    assert behavior_registry.behavior("pdns_recur", "master") is PdnsRecursorMasterBehavior
    assert section_registry.section("pdns_recur").__name__ == "PdnsRecursorSection"
    assert includer_registry.includer("pdns_recur").__name__ == "PdnsRecursorIncluder"


def test_util_mode_is_project_level_and_validated():
    config = ConfigModel(name="test", inet="10.0.0.0/24", util_mode="docker")
    assert config.util_mode == "docker"

    with pytest.raises(ValueError):
        ConfigModel(name="test", inet="10.0.0.0/24", util_mode="container")
