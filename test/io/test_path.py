# tests/test_path.py

import pytest
from pathlib import PurePosixPath
from dnsbuilder.io.path import DNSBPath


class TestDNSBPath:
    """Unit tests for the DNSBPath class."""

    @pytest.mark.parametrize(
        "path_str, expected_protocol, expected_host, expected_path_posix",
        [
            ("local/file.txt", "file", "", "local/file.txt"),
            ("/absolute/path", "file", "", "/absolute/path"),
            ("file:///absolute/path", "file", "", "/absolute/path"),
            ("resource:/data/config.yml", "resource", "", "/data/config.yml"),
            ("http://example.com/data/file", "http", "example.com", "/data/file"),
            ("s3://my-bucket/prefix/key", "s3", "my-bucket", "/prefix/key"),
            ("/", "file", "", "/"),
        ],
    )
    def test_initialization_parsing(
        self, path_str, expected_protocol, expected_host, expected_path_posix
    ):
        """Tests that DNSBPath correctly parses various path formats upon creation."""
        path = DNSBPath(path_str)
        assert path.protocol == expected_protocol
        assert path.host == expected_host
        assert path.__path__() == expected_path_posix

    def test_protocol_checkers(self):
        assert DNSBPath("local/file").is_file()
        assert DNSBPath("resource:/path").is_resource()
        assert DNSBPath("http://host/path").is_http()
        assert not DNSBPath("local/file").is_resource()
        assert not DNSBPath("resource:/path").is_file()

    def test_parent_preserves_attributes(self):
        path = DNSBPath("s3://my-bucket/prefix/key")
        parent = path.parent
        assert isinstance(parent, DNSBPath)
        assert parent.protocol == "s3"
        assert parent.host == "my-bucket"
        assert str(parent) == "s3://my-bucket/prefix"
        path_root = DNSBPath("resource:/")
        assert str(path_root.parent) == "resource:/"

    def test_joinpath_and_truediv_preserves_attributes(self):
        base = DNSBPath("http://example.com/data/")
        joined_jp = base.joinpath("subdir", "file.txt")
        assert isinstance(joined_jp, DNSBPath)
        assert joined_jp.protocol == "http"
        assert joined_jp.host == "example.com"
        assert str(joined_jp) == "http://example.com/data/subdir/file.txt"
        joined_td = base / "subdir" / "file.txt"
        assert str(joined_td) == "http://example.com/data/subdir/file.txt"

    def test_rtruediv_operator(self):
        rel_path = DNSBPath("subdir/file.txt")
        result = "prefix" / rel_path
        assert isinstance(result, DNSBPath)
        assert result.protocol == "file"
        assert str(result) == "prefix/subdir/file.txt"
        abs_path = DNSBPath("/etc/passwd")
        from dnsbuilder.exceptions import InvalidPathError
        with pytest.raises(
            InvalidPathError, match="Can not join absolute path with relative path"
        ):
            "prefix" / abs_path

    @pytest.mark.parametrize(
        "path_str, expected_str",
        [
            # FIX: All expected outputs should be POSIX style, as this is our design choice.
            ("local/file", "local/file"),
            ("/abs/file", "/abs/file"),
            # Note: Windows paths are converted to POSIX in __path__() but displayed as-is in __str__() for file protocol
            # (r"C:\Users\test", "C:/Users/test"),
            ("resource:/data", "resource:/data"),
            ("http://host.com/path", "http://host.com/path"),
        ],
    )
    def test_str_representation(self, path_str, expected_str):
        path = DNSBPath(path_str)
        assert str(path) == expected_str

    def test_repr_representation(self):
        path = DNSBPath("resource:/data")
        assert repr(path) == "DNSBPath('resource:/data')"

    @pytest.mark.parametrize(
        "path_str, is_origin, expected_need_copy",
        [
            ("local/file", True, False),
            ("/abs/file", True, False),
            ("resource:/path", True, False),
            ("resource:/path", False, True),
            ("http://host/path", False, True),
            ("local/file", False, True),
            ("/abs/file", False, False),
            (r"C:\abs\file", False, False),
        ],
    )
    def test_need_copy_logic(self, path_str, is_origin, expected_need_copy):
        path = DNSBPath(path_str, is_origin=is_origin)
        assert path.need_copy == expected_need_copy

    @pytest.mark.parametrize(
        "path_str, is_origin, expected_need_check",
        [
            ("local/file", True, False),
            ("local/file", False, True),
        ],
    )
    def test_need_check_logic(self, path_str, is_origin, expected_need_check):
        path = DNSBPath(path_str, is_origin=is_origin)
        assert path.need_check == expected_need_check

    def test_is_absolute(self):
        assert DNSBPath("/local/file").is_absolute()
        assert not DNSBPath("local/file").is_absolute()
        assert DNSBPath(r"C:\Windows").is_absolute()
        assert DNSBPath("resource:/path/to/data").is_absolute()
        assert not DNSBPath("http://example.com").is_absolute()
        assert DNSBPath("http://example.com/").is_absolute()

    def test_git_protocol_parsing(self):
        """Test git protocol parsing with fragment and query"""
        path = DNSBPath("git://github.com/user/repo?ref=main#config/subdir/file.yml")
        assert path.protocol == "git"
        assert path.host == "github.com"
        assert path.__path__() == "/user/repo"
        assert path.fragment == "config/subdir/file.yml"
        assert path.query_str == "ref=main"
        assert path.query["ref"] == ["main"]

    @pytest.mark.parametrize(
        "path_str, expected_parent_str, expected_fragment",
        [
            # Git protocol - parent operates on fragment
            (
                "git://github.com/user/repo?ref=main#config/subdir/file.yml",
                "git://github.com/user/repo?ref=main#config/subdir",
                "config/subdir"
            ),
            (
                "git://github.com/user/repo?ref=main#a/b/c/d.yml",
                "git://github.com/user/repo?ref=main#a/b/c",
                "a/b/c"
            ),
            # Resource protocol - parent operates on path_part
            (
                "resource:/images/defaults/bind.yml",
                "resource:/images/defaults",
                ""
            ),
            (
                "resource:/a/b/c",
                "resource:/a/b",
                ""
            ),
            # HTTP protocol - parent operates on path_part
            (
                "http://example.com/api/v1/resource",
                "http://example.com/api/v1",
                ""
            ),
            # S3 protocol - parent operates on path_part
            (
                "s3://my-bucket/data/configs/app.yml",
                "s3://my-bucket/data/configs",
                ""
            ),
            # File protocol - parent operates on path_part
            (
                "/home/user/project/config/app.yml",
                "/home/user/project/config",
                ""
            ),
        ],
    )
    def test_parent_operations_by_protocol(self, path_str, expected_parent_str, expected_fragment):
        """Test that parent operation works correctly for different protocols"""
        path = DNSBPath(path_str)
        parent = path.parent
        
        assert isinstance(parent, DNSBPath)
        assert str(parent) == expected_parent_str
        assert parent.fragment == expected_fragment

    @pytest.mark.parametrize(
        "base_str, join_args, expected_str, expected_fragment",
        [
            # Git protocol - joinpath operates on fragment
            (
                "git://github.com/user/repo?ref=main#config",
                ("subdir", "file.yml"),
                "git://github.com/user/repo?ref=main#config/subdir/file.yml",
                "config/subdir/file.yml"
            ),
            (
                "git://github.com/user/repo?ref=main#config",
                ("aliyun", "attack.yml"),
                "git://github.com/user/repo?ref=main#config/aliyun/attack.yml",
                "config/aliyun/attack.yml"
            ),
            (
                "git://github.com/user/repo?ref=main#",
                ("config", "file.yml"),
                "git://github.com/user/repo?ref=main#config/file.yml",
                "config/file.yml"
            ),
            # Resource protocol - joinpath operates on path_part
            (
                "resource:/images",
                ("rules", "bind.yml"),
                "resource:/images/rules/bind.yml",
                ""
            ),
            # HTTP protocol - joinpath operates on path_part
            (
                "http://example.com/api",
                ("v1", "resource"),
                "http://example.com/api/v1/resource",
                ""
            ),
            # S3 protocol - joinpath operates on path_part
            (
                "s3://my-bucket/data",
                ("configs", "app.yml"),
                "s3://my-bucket/data/configs/app.yml",
                ""
            ),
            # File protocol - joinpath operates on path_part
            (
                "/home/user/project",
                ("config", "app.yml"),
                "/home/user/project/config/app.yml",
                ""
            ),
        ],
    )
    def test_joinpath_operations_by_protocol(self, base_str, join_args, expected_str, expected_fragment):
        """Test that joinpath operation works correctly for different protocols"""
        base = DNSBPath(base_str)
        joined = base.joinpath(*join_args)
        
        assert isinstance(joined, DNSBPath)
        assert str(joined) == expected_str
        assert joined.fragment == expected_fragment

    @pytest.mark.parametrize(
        "base_str, div_args, expected_str, expected_fragment",
        [
            # Git protocol - / operator operates on fragment
            (
                "git://github.com/user/repo?ref=main#config",
                ["aliyun", "attack.yml"],
                "git://github.com/user/repo?ref=main#config/aliyun/attack.yml",
                "config/aliyun/attack.yml"
            ),
            # Resource protocol - / operator operates on path_part
            (
                "resource:/images",
                ["defaults", "bind.yml"],
                "resource:/images/defaults/bind.yml",
                ""
            ),
            # S3 protocol - / operator operates on path_part
            (
                "s3://my-bucket/data",
                ["new", "file.yml"],
                "s3://my-bucket/data/new/file.yml",
                ""
            ),
            # File protocol - / operator operates on path_part
            (
                "/home/user/project",
                ["other", "file.yml"],
                "/home/user/project/other/file.yml",
                ""
            ),
        ],
    )
    def test_truediv_operations_by_protocol(self, base_str, div_args, expected_str, expected_fragment):
        """Test that / operator works correctly for different protocols"""
        base = DNSBPath(base_str)
        result = base
        for arg in div_args:
            result = result / arg
        
        assert isinstance(result, DNSBPath)
        assert str(result) == expected_str
        assert result.fragment == expected_fragment

    def test_git_relative_path_resolution(self):
        """Test relative path resolution for git protocol (like ../aliyun/attack)"""
        current = DNSBPath("git://github.com/user/repo?ref=main#config/project/main.yml")
        parent = current.parent.parent  # Go up to config/
        sibling = parent / "aliyun" / "attack"
        
        assert sibling.fragment == "config/aliyun/attack"
        assert str(sibling) == "git://github.com/user/repo?ref=main#config/aliyun/attack"

    def test_git_multiple_parent_levels(self):
        """Test multiple parent operations on git protocol"""
        path = DNSBPath("git://github.com/user/repo?ref=main#a/b/c/d.yml")
        parent1 = path.parent
        parent2 = parent1.parent
        parent3 = parent2.parent
        
        assert parent1.fragment == "a/b/c"
        assert parent2.fragment == "a/b"
        assert parent3.fragment == "a"
        assert str(parent3) == "git://github.com/user/repo?ref=main#a"

if __name__ == "__main__":
    pytest.main()