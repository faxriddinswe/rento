"""S3-compatible object storage (MinIO in dev/prod) behind a small interface."""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.config import get_settings


@dataclass(frozen=True)
class PresignedPost:
    url: str
    fields: dict[str, str]
    key: str


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str


class Storage(Protocol):
    async def ping(self) -> None: ...
    async def ensure_bucket(self) -> None: ...
    async def presign_post(
        self, key: str, content_type: str, max_bytes: int, expires: int = 600
    ) -> PresignedPost: ...
    async def presign_get(self, key: str, expires: int = 600) -> str: ...
    async def head(self, key: str) -> ObjectInfo | None: ...
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...


class S3Storage:
    def __init__(self) -> None:
        s = get_settings()
        self.bucket = s.s3_bucket
        cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"})
        common: dict[str, Any] = dict(
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name=s.s3_region,
            config=cfg,
        )
        self._internal = boto3.client("s3", endpoint_url=s.s3_endpoint_url, **common)
        # Signing is purely local; the public client signs URLs the browser can reach.
        self._public = boto3.client("s3", endpoint_url=s.s3_public_endpoint_url, **common)

    async def ping(self) -> None:
        await asyncio.to_thread(self._internal.head_bucket, Bucket=self.bucket)

    async def ensure_bucket(self) -> None:
        def _do() -> None:
            try:
                self._internal.head_bucket(Bucket=self.bucket)
            except ClientError:
                self._internal.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(_do)

    async def presign_post(
        self, key: str, content_type: str, max_bytes: int, expires: int = 600
    ) -> PresignedPost:
        def _do() -> dict[str, Any]:
            return dict(
                self._public.generate_presigned_post(
                    Bucket=self.bucket,
                    Key=key,
                    Fields={"Content-Type": content_type},
                    Conditions=[
                        {"Content-Type": content_type},
                        ["content-length-range", 1, max_bytes],
                    ],
                    ExpiresIn=expires,
                )
            )

        r = await asyncio.to_thread(_do)
        return PresignedPost(url=r["url"], fields=r["fields"], key=key)

    async def presign_get(self, key: str, expires: int = 600) -> str:
        def _do() -> str:
            return str(
                self._public.generate_presigned_url(
                    "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires
                )
            )

        return await asyncio.to_thread(_do)

    async def head(self, key: str) -> ObjectInfo | None:
        def _do() -> ObjectInfo | None:
            try:
                r = self._internal.head_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                    return None
                raise
            return ObjectInfo(size=int(r["ContentLength"]), content_type=str(r["ContentType"]))

        return await asyncio.to_thread(_do)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._internal.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    async def get(self, key: str) -> bytes:
        def _do() -> bytes:
            return bytes(self._internal.get_object(Bucket=self.bucket, Key=key)["Body"].read())

        return await asyncio.to_thread(_do)


@lru_cache
def get_storage() -> Storage:
    return S3Storage()
