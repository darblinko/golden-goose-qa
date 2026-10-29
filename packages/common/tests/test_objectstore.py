"""S3 client construction: static keys locally, SDK default chain in cloud."""

import hashlib

import boto3
import botocore.exceptions
import pytest
from gg_common.objectstore import (
    LocalObjectStore,
    ObjectIntegrityError,
    S3ObjectStore,
    read_verified,
)
from gg_common.settings import ObjectStoreSettings
from pydantic import SecretStr


def _capture_client_kwargs(monkeypatch):
    captured: dict = {}

    def fake_client(service: str, **kwargs):
        captured["service"] = service
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(boto3, "client", fake_client)
    return captured


def test_local_settings_pass_endpoint_and_static_keys(monkeypatch):
    captured = _capture_client_kwargs(monkeypatch)
    S3ObjectStore(ObjectStoreSettings())
    assert captured["endpoint_url"] == "http://localhost:8333"
    assert captured["aws_access_key_id"] == "gg_dev_access"
    assert captured["aws_secret_access_key"] == "gg_dev_secret"


def test_empty_endpoint_and_key_defer_to_sdk_defaults(monkeypatch):
    captured = _capture_client_kwargs(monkeypatch)
    S3ObjectStore(ObjectStoreSettings(endpoint_url="", access_key="", secret_key=SecretStr("")))
    assert "endpoint_url" not in captured
    assert "aws_access_key_id" not in captured
    assert "aws_secret_access_key" not in captured
    assert captured["region_name"] == "us-east-1"


class _FakeS3Client:
    """Minimal boto3 S3 stand-in recording versioning calls."""

    def __init__(self, *, versioning_error: Exception | None = None) -> None:
        self.versioning_calls: list[dict] = []
        self._versioning_error = versioning_error

    def list_buckets(self):
        return {"Buckets": [{"Name": "gg-documents"}]}

    def put_bucket_versioning(self, *, Bucket, VersioningConfiguration):
        self.versioning_calls.append({"bucket": Bucket, "config": VersioningConfiguration})
        if self._versioning_error is not None:
            raise self._versioning_error


def _store_with_fake(monkeypatch, client):
    monkeypatch.setattr(boto3, "client", lambda service, **kwargs: client)
    return S3ObjectStore(ObjectStoreSettings())


def test_ensure_bucket_enables_versioning(monkeypatch):
    client = _FakeS3Client()
    store = _store_with_fake(monkeypatch, client)
    store.ensure_bucket("gg-documents")
    assert client.versioning_calls == [{"bucket": "gg-documents", "config": {"Status": "Enabled"}}]


def test_ensure_bucket_tolerates_backend_without_versioning(monkeypatch):
    error = botocore.exceptions.ClientError(
        {"Error": {"Code": "NotImplemented", "Message": "unsupported"}},
        "PutBucketVersioning",
    )
    client = _FakeS3Client(versioning_error=error)
    store = _store_with_fake(monkeypatch, client)
    # A backend that rejects versioning must not break bucket setup.
    store.ensure_bucket("gg-documents")
    assert client.versioning_calls  # attempted, then swallowed


def test_read_verified_returns_bytes_when_hash_matches(tmp_path):
    store = LocalObjectStore(tmp_path)
    data = b"controlled document bytes"
    digest = hashlib.sha256(data).hexdigest()
    store.put("gg-documents", "SOP-004/hash/file.pdf", data)

    result = read_verified(store, "gg-documents", "SOP-004/hash/file.pdf", expected_sha256=digest)
    assert result == data


def test_read_verified_fails_closed_on_hash_mismatch(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put("gg-documents", "SOP-004/hash/file.pdf", b"tampered bytes")

    with pytest.raises(ObjectIntegrityError):
        read_verified(store, "gg-documents", "SOP-004/hash/file.pdf", expected_sha256="0" * 64)
