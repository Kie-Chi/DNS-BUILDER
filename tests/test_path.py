import unittest
from pathlib import Path
import shutil
import tempfile
from dnsbuilder.utils.path import DNSBPath, add_resource, rm_resource
from dnsbuilder.exceptions import VolumeNotFoundError
import os

class TestDNSBPath(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for testing file system paths
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_dir_path = Path(self.test_dir.name)

        # Create dummy files and directories for resource testing
        self.resources_path = self.test_dir_path / 'resources'
        self.resources_path.mkdir()
        (self.resources_path / 'configs').mkdir()
        (self.resources_path / 'data').mkdir()
        (self.resources_path / 'configs' / 'config.txt').write_text('config')
        (self.resources_path / 'data' / 'data.txt').write_text('data')

        # Mocking importlib.resources is complex, so we'll adjust the path finding
        # to point to our test resources. This is a pragmatic approach for testing.
        import dnsbuilder.utils.path
        
        # The original mock was incorrect. This one correctly maps the package name
        # (e.g., 'dnsbuilder.resources.configs') to the test directory structure.
        self.original_resources_files = dnsbuilder.utils.path.resources.files
        dnsbuilder.utils.path.resources.files = lambda package: self.test_dir_path / Path(*package.split('.')[1:])


    def tearDown(self):
        # Cleanup the temporary directory
        self.test_dir.cleanup()
        # Restore the original resources.files function
        import dnsbuilder.utils.path
        dnsbuilder.utils.path.resources.files = self.original_resources_files

    def test_normal_paths(self):
        # Test absolute paths
        abs_path_str = str(self.test_dir_path / 'test.txt')
        p_abs = DNSBPath(abs_path_str)
        self.assertFalse(p_abs.is_resource)
        self.assertTrue(p_abs.is_absolute())
        self.assertEqual(str(p_abs), abs_path_str)

        # Test relative paths
        rel_path_str = 'some/relative/path.txt'
        p_rel = DNSBPath(rel_path_str)
        self.assertFalse(p_rel.is_resource)
        self.assertFalse(p_rel.is_absolute())
        # Normalize path separators for cross-platform compatibility
        self.assertEqual(str(p_rel).replace(os.sep, '/'), rel_path_str)

    def test_resource_paths(self):
        # Test resource file. The path should be relative to the 'configs' resource folder.
        p_res_file = DNSBPath('resource:config.txt')
        self.assertTrue(p_res_file.is_resource)
        self.assertFalse(p_res_file.is_absolute())
        self.assertTrue(p_res_file.exists())
        self.assertEqual(p_res_file.read_text(), 'config')

        # Test resource directory. This should point to the root of the default resource folder.
        p_res_dir = DNSBPath('resource:')
        self.assertTrue(p_res_dir.is_resource)
        self.assertTrue(p_res_dir.is_dir())

    def test_resource_parent(self):
        p = DNSBPath('resource:/data/data.txt')
        parent = p.parent
        self.assertTrue(parent.is_resource)
        self.assertEqual(parent.origin, 'resource:/data')

    def test_resource_truediv(self):
        p = DNSBPath('resource:/data')
        child = p / 'data.txt'
        self.assertTrue(child.is_resource)
        self.assertEqual(child.origin, 'resource:/data/data.txt')
        self.assertTrue(child.exists())

    def test_invalid_resource(self):
        with self.assertRaises(VolumeNotFoundError):
            DNSBPath('resource:nonexistent/file.txt')

    def test_add_rm_resource(self):
        path = 'my/path'
        res_path = add_resource(path)
        self.assertEqual(res_path, 'resource:my/path')
        self.assertEqual(rm_resource(res_path), 'my/path')
        # Test idempotency
        self.assertEqual(add_resource(res_path), res_path)
        self.assertEqual(rm_resource(path), path)

if __name__ == '__main__':
    unittest.main()