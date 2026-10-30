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


def _client_error(code: str, operation: str) -> botocore.exceptions.ClientError:
    return botocore.exceptions.ClientError({"Error": {"Code": code, "Message": code}}, operation)


class _FakeS3Client:
    """Minimal boto3 S3 stand-in recording bucket and versioning calls.

    list_buckets raises AccessDenied, as the AWS task policy denies
    account-wide listing (infra/terraform/aws/iam.tf)."""

    def __init__(
        self,
        *,
        versioning_error: Exception | None = None,
        existing: frozenset[str] = frozenset({"gg-documents"}),
        head_error_code: str | None = None,
    ) -> None:
        self.versioning_calls: list[dict] = []
        self.created: list[str] = []
        self._versioning_error = versioning_error
        self._existing = set(existing)
        self._head_error_code = head_error_code

    def list_buckets(self):
        raise _client_error("AccessDenied", "ListBuckets")

    def head_bucket(self, *, Bucket):
        if self._head_error_code is not None:
            raise _client_error(self._head_error_code, "HeadBucket")
        if Bucket not in self._existing:
            raise _client_error("404", "HeadBucket")
        return {}

    def create_bucket(self, *, Bucket):
        self.created.append(Bucket)
        self._existing.add(Bucket)

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


def test_ensure_bucket_checks_existing_bucket_without_listing_account(monkeypatch):
    client = _FakeS3Client()
    store = _store_with_fake(monkeypatch, client)
    store.ensure_bucket("gg-documents")
    assert client.created == []


def test_ensure_bucket_creates_missing_bucket(monkeypatch):
    client = _FakeS3Client(existing=frozenset())
    store = _store_with_fake(monkeypatch, client)
    store.ensure_bucket("gg-artifacts")
    assert client.created == ["gg-artifacts"]


def test_ensure_bucket_forbidden_is_an_explicit_error(monkeypatch):
    client = _FakeS3Client(head_error_code="403")
    store = _store_with_fake(monkeypatch, client)
    with pytest.raises(PermissionError, match="gg-documents"):
        store.ensure_bucket("gg-documents")
    assert client.created == []


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
