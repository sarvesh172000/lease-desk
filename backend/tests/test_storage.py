import pytest

from app.docs.storage import LocalStorage, sha256_of


def test_roundtrip(tmp_path):
    s = LocalStorage(tmp_path)
    key = s.put(b"lease bytes")
    assert s.get(key) == b"lease bytes"


def test_key_is_the_content_hash(tmp_path):
    s = LocalStorage(tmp_path)
    assert s.put(b"lease bytes") == sha256_of(b"lease bytes")


def test_storing_twice_is_one_document(tmp_path):
    s = LocalStorage(tmp_path)
    a = s.put(b"same")
    b = s.put(b"same")
    assert a == b
    assert list(s.iter_keys()) == [a]


def test_different_bytes_different_key(tmp_path):
    s = LocalStorage(tmp_path)
    assert s.put(b"one") != s.put(b"two")


def test_missing_document_raises(tmp_path):
    with pytest.raises(KeyError):
        LocalStorage(tmp_path).get("0" * 64)


def test_key_cannot_escape_the_store(tmp_path):
    s = LocalStorage(tmp_path)
    for bad in ("../../etc/passwd", "/etc/passwd", "zz" * 32, "abc"):
        with pytest.raises(ValueError):
            s.get(bad)


def test_put_file(tmp_path):
    src = tmp_path / "lease.pdf"
    src.write_bytes(b"%PDF-1.7 fake")
    s = LocalStorage(tmp_path / "store")
    assert s.get(s.put_file(src)) == b"%PDF-1.7 fake"
