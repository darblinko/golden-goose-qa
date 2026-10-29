"""Object store seam. S3-compatible (SeaweedFS locally, S3/Blob in cloud) plus a
local-filesystem implementation for tests."""

import hashlib
import logging
from abc import ABC, abstractmethod
from pathlib import Path

from gg_common.settings import ObjectStoreSettings

_log = logging.getLogger(__name__)


class ObjectIntegrityError(Exception):
    """Stored bytes do not match the content hash the registry recorded for
    them. Raised instead of returning content that may be corrupt or tampered
    with, so an integrity failure fails closed rather than serving bad bytes."""


class ObjectStore(ABC):
    @abstractmethod
    def put(self, bucket: str, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, bucket: str, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, bucket: str, key: str) -> bool: ...

    @abstractmethod
    def list_keys(self, bucket: str, prefix: str = "") -> list[str]: ...


class S3ObjectStore(ObjectStore):
    def __init__(self, settings: ObjectStoreSettings) -> None:
        import boto3

        # Empty endpoint/key means native S3 with the SDK's default credential
        # chain (ECS task role, instance profile, env) instead of static keys.
        kwargs: dict[str, str] = {"region_name": settings.region}
        if settings.endpoint_url:
            kwargs["endpoint_url"] = settings.endpoint_url
        if settings.access_key:
            kwargs["aws_access_key_id"] = settings.access_key
            kwargs["aws_secret_access_key"] = settings.secret_key.get_secret_value()
        self._client = boto3.client("s3", **kwargs)

    def ensure_bucket(self, bucket: str) -> None:
        existing = {b["Name"] for b in self._client.list_buckets().get("Buckets", [])}
        if bucket not in existing:
            self._client.create_bucket(Bucket=bucket)
        self._enable_versioning(bucket)

    def _enable_versioning(self, bucket: str) -> None:
        """Turn on bucket versioning as defense-in-depth so an overwrite or
        delete of an original preserves the prior object version. Backends
        differ (native S3 and MinIO support it; SeaweedFS may reject it), so a
        failure is logged and tolerated: the enforced immutability guarantee is
        content-addressed, write-once keys plus read-time hash verification
        (`read_verified`), which hold regardless of backend versioning support."""
        import botocore.exceptions

        try:
            self._client.put_bucket_versioning(
                Bucket=bucket,
                VersioningConfiguration={"Status": "Enabled"},
            )
        except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as exc:
            _log.info("bucket versioning not enabled for %s: %s", bucket, exc)

    def put(self, bucket: str, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=bucket, Key=key, Body=data)

    def get(self, bucket: str, key: str) -> bytes:
        return self._client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def exists(self, bucket: str, key: str) -> bool:
        import botocore.exceptions

        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys


class LocalObjectStore(ObjectStore):
    """Filesystem-backed store for unit tests and offline development."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, bucket: str, key: str) -> Path:
        path = (self.root / bucket / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"key escapes store root: {key}")
        return path

    def put(self, bucket: str, key: str, data: bytes) -> None:
        path = self._path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, bucket: str, key: str) -> bytes:
        return self._path(bucket, key).read_bytes()

    def exists(self, bucket: str, key: str) -> bool:
        return self._path(bucket, key).is_file()

    def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        base = self.root / bucket
        if not base.is_dir():
            return []
        return sorted(
            str(p.relative_to(base))
            for p in base.rglob("*")
            if p.is_file() and str(p.relative_to(base)).startswith(prefix)
        )


def read_verified(store: ObjectStore, bucket: str, key: str, *, expected_sha256: str) -> bytes:
    """Read an object and confirm its SHA-256 matches the registry's recorded
    content hash before returning it.

    The registry, not the object store, is the source of truth for a document's
    identity, so every read-back of an original is verified against the hash
    ingestion recorded. A mismatch — corruption, a swapped object, tampering —
    raises ObjectIntegrityError instead of returning the bytes."""
    data = store.get(bucket, key)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha256:
        raise ObjectIntegrityError(
            f"integrity check failed for {bucket}/{key}: "
            f"registry hash {expected_sha256}, stored bytes hash {actual}"
        )
    return data
