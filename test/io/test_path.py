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
        with pytest.raises(
            ValueError, match="Can not join absolute path with relative path"
        ):
            "prefix" / abs_path

    @pytest.mark.parametrize(
        "path_str, expected_str",
        [
            # FIX: All expected outputs should be POSIX style, as this is our design choice.
            ("local/file", "local/file"),
            ("/abs/file", "/abs/file"),
            (r"C:\Users\test", "C:/Users/test"),
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

if __name__ == "__main__":
    pytest.main()