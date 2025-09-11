import pytest
import yaml
from pathlib import Path
from dnsbuilder.config import Config
from dnsbuilder.exceptions import ConfigError, CircularDependencyError
import copy

BASE_CONFIG = {
    'name': 'my-dns-project',
    'inet': '172.28.0.0/24',
    'images': [
        {
            'name': 'bind-base',
            'software': 'bind',
            'version': '9.18.18',
            'from': 'ubuntu:20.04'
        },
        {
            'name': 'unbound-custom',
            'ref': 'unbound:1.17.0'
        }
    ],
    'builds': {
        'recursor': {
            'image': 'bind-base',
            'address': '172.28.0.10'
        },
        'forwarder': {
            'ref': 'recursor',
            'image': 'unbound-custom'
        }
    }
}

@pytest.fixture
def create_config_file(tmp_path: Path):
    """A pytest fixture to create a temporary config.yml file."""
    def _create_file(config_data: dict) -> Path:
        config_file = tmp_path / "config.yml"
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f)
        return config_file
    return _create_file

class TestConfigLoading:
    """Tests for basic loading and validation success/failure."""

    def test_load_valid_config_successfully(self, create_config_file):
        """Should load a well-formed config without raising exceptions."""
        config_path = create_config_file(BASE_CONFIG)
        try:
            config = Config(str(config_path))
            assert config.name == 'my-dns-project'
            assert len(config.images_config) == 2
            assert 'recursor' in config.builds_config
        except Exception as e:
            pytest.fail(f"Valid config failed to load: {e}")

    def test_missing_top_level_key_raises_error(self, create_config_file):
        """Should raise ConfigError if a required top-level key is missing."""
        invalid_config = copy.deepcopy(BASE_CONFIG)
        del invalid_config['images']
        
        config_path = create_config_file(invalid_config)
        
        with pytest.raises(ConfigError, match="images\n  Field required"):
            Config(str(config_path))

    def test_file_not_found_raises_error(self):
        """Should raise FileNotFoundError for a non-existent file."""
        with pytest.raises(FileNotFoundError):
            Config("non_existent_file.yml")

    def test_invalid_yaml_raises_error(self, tmp_path):
        """Should raise ConfigError for malformed YAML."""
        config_file = tmp_path / "invalid.yml"
        config_file.write_text("key: value: another") # Invalid YAML
        
        with pytest.raises(ConfigError, match="Error parsing YAML file"):
            Config(str(config_file))


class TestConfigValidationLogic:
    """Tests for more complex validation logic like dependencies and cycles."""

    def test_image_circular_dependency_raises_error(self, create_config_file):
        """Should raise CircularDependencyError for circular refs in images."""
        invalid_config = copy.deepcopy(BASE_CONFIG)
        invalid_config['images'].extend([
            {'name': 'img-a', 'ref': 'img-b'},
            {'name': 'img-b', 'ref': 'img-a'},
        ])
        config_path = create_config_file(invalid_config)
        
        with pytest.raises(CircularDependencyError, match="Circular dependency in images: 'img-[ab]' -> 'img-[ab]'"):
            Config(str(config_path))

    def test_build_circular_dependency_raises_error(self, create_config_file):
        """Should raise CircularDependencyError for circular refs in builds."""
        invalid_config = copy.deepcopy(BASE_CONFIG)
        invalid_config['builds'].update({
            'build-a': {'ref': 'build-b', 'image': 'bind-base'},
            'build-b': {'ref': 'build-a', 'image': 'bind-base'},
        })
        config_path = create_config_file(invalid_config)
        
        with pytest.raises(CircularDependencyError, match="Circular dependency in builds: 'build-[ab]' -> 'build-[ab]'"):
            Config(str(config_path))

    def test_image_ref_and_software_conflict_raises_error(self, create_config_file):
        """Should raise ConfigError if an image has both 'ref' and 'software'."""
        invalid_config = copy.deepcopy(BASE_CONFIG)
        # Modify the second image to have conflicting keys
        invalid_config['images'][1] = {
            'name': 'conflicting-image',
            'ref': 'bind-base',
            'software': 'unbound' # This conflicts with 'ref'
        }
        config_path = create_config_file(invalid_config)
        
        with pytest.raises(ConfigError, match="'ref' cannot be used with 'software', 'version', or 'from'"):
            Config(str(config_path))
            
    def test_duplicate_image_name_raises_error(self, create_config_file):
        """Should raise ConfigError on duplicate image names."""
        invalid_config = copy.deepcopy(BASE_CONFIG)
        invalid_config['images'].append({
            'name': 'bind-base', # Duplicate name
            'software': 'unbound',
            'version': '1.17.0',
            'from': 'alpine:latest'
        })
        config_path = create_config_file(invalid_config)

        with pytest.raises(ConfigError, match="Duplicate image names found: bind-base"):
            Config(str(config_path))