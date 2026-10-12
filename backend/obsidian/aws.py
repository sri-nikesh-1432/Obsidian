"""AWS resource access.

All DynamoDB / S3 / KMS calls go through this module.

In local development (OBSIDIAN_LOCAL_AWS=true) the AWS SDK is intercepted by
moto, so the application code path is byte-for-byte the same one that runs
against real AWS. In production the same boto3 clients talk to real services.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from urllib.parse import quote

import boto3
import httpx
from boto3.dynamodb.conditions import Key, Attr  # noqa: F401  (re-exported for handlers)
from botocore.config import Config

from .config import settings
from . import persistence

_lock = threading.RLock()
_mock = None
_resources_ready = False
_clients: dict = {}
_resources: dict = {}

P = settings.table_prefix

TABLES: dict[str, dict] = {
    "users": {
        "table": f"{P}-users",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
    "profiles": {
        "table": f"{P}-profiles",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
    "sessions": {
        "table": f"{P}-sessions",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
    "mfa": {"table": f"{P}-mfa", "key": ("pk", "sk"), "gsis": []},
    "documents": {
        "table": f"{P}-documents",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
    "shares": {
        "table": f"{P}-shares",
        "key": ("pk", "sk"),
        "gsis": [
            {"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"},
            {"name": "gsi2", "hash": "gsi2pk", "range": "gsi2sk"},
            {"name": "gsi3", "hash": "gsi3pk", "range": "gsi3sk"},
        ],
    },
    # Student connection graph: one directed edge per (follower -> followee).
    # gsi1 indexes edges by target so incoming requests / followers can be
    # listed without a scan.
    "connections": {
        "table": f"{P}-connections",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
    # Faculty-led groups + group chat. A single item collection per group:
    #   pk=GROUP#<id>  sk=META          -> group metadata
    #   pk=GROUP#<id>  sk=MEMBER#<uid>  -> membership row
    #   pk=GROUP#<id>  sk=MSG#<ts>#<id> -> chat message (chronological)
    # gsi1 lists groups owned by a faculty member; gsi2 lists the groups a
    # student belongs to.
    "groups": {
        "table": f"{P}-groups",
        "key": ("pk", "sk"),
        "gsis": [
            {"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"},
            {"name": "gsi2", "hash": "gsi2pk", "range": "gsi2sk"},
        ],
    },
    "audit": {
        "table": f"{P}-audit",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
    "rag": {"table": f"{P}-rag", "key": ("pk", "sk"), "gsis": []},
    "config": {"table": f"{P}-config", "key": ("pk", "sk"), "gsis": []},
    "ratelimits": {"table": f"{P}-ratelimits", "key": ("pk", "sk"), "gsis": []},
    "devmail": {"table": f"{P}-devmail", "key": ("pk", "sk"), "gsis": []},
    # Storage billing: one row per Razorpay order plus an entitlement row per
    # account. gsi1 keys orders by razorpay order id for webhook lookups.
    "billing": {
        "table": f"{P}-billing",
        "key": ("pk", "sk"),
        "gsis": [{"name": "gsi1", "hash": "gsi1pk", "range": "gsi1sk"}],
    },
}


def _session() -> boto3.session.Session:
    return boto3.session.Session(region_name=settings.aws_region)


def _ensure_mock() -> None:
    global _mock
    if not settings.local_aws:
        return
    with _lock:
        if _mock is None:
            from moto import mock_aws
            config = None
            if settings.r2_configured:
                # Let the R2 endpoint escape moto's process-wide interception
                # while DynamoDB/KMS stay emulated in-process. Without this the
                # S3 object calls would be answered by moto instead of Cloudflare.
                import re
                endpoint = settings.r2_endpoint.rstrip("/")
                config = {"core": {"passthrough": {"urls": [re.escape(endpoint)], "services": []}}}
            _mock = mock_aws(config=config) if config else mock_aws()
            _mock.start()


def get_client(service: str):
    """Return a cached boto3 client. Moto intercepts calls when running locally.

    When durable state is enabled the emulated KMS is replaced by a software KMS
    whose root key persists in the Cloudflare object store, so document keys stay
    decryptable across restarts.
    """
    if service == "kms" and persistence.enabled():
        return persistence.software_kms()
    _ensure_mock()
    with _lock:
        if service not in _clients:
            _clients[service] = _session().client(service)
        return _clients[service]


def get_resource(service: str):
    _ensure_mock()
    with _lock:
        if service not in _resources:
            _resources[service] = _session().resource(service)
        return _resources[service]


def _r2_client():
    """A boto3 S3 client pointed at Cloudflare R2 (S3-compatible API).

    R2 speaks the S3 protocol, so every object operation in the codebase works
    unchanged — only the endpoint and credentials differ. Path-style addressing
    is required because R2 buckets are not DNS-virtual-hosted per account.
    """
    with _lock:
        if "r2" not in _clients:
            _clients["r2"] = boto3.session.Session().client(
                "s3",
                endpoint_url=settings.r2_endpoint,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name=settings.r2_region or "auto",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return _clients["r2"]


def storage_client():
    """The object-store client: Cloudflare KV / R2 when configured, else S3/moto.

    Handlers must use this (not ``get_client("s3")``) so the object store can be
    redirected to a Cloudflare backend purely by configuration.
    """
    if settings.kv_configured:
        return _kv_client()
    if settings.r2_configured:
        return _r2_client()
    return get_client("s3")


class _KVBody:
    """Minimal file-like wrapper so boto3-style ``resp["Body"].read()`` works."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __bytes__(self) -> bytes:
        return self._data


class _KVClient:
    """boto3-S3-shaped shim backed by the Cloudflare Workers KV REST API.

    Workers KV is not S3-compatible, so this exposes just the three operations
    the codebase issues (``put_object`` / ``get_object`` / ``delete_object``)
    against a single namespace. The ``Bucket`` argument is ignored — the vault
    uses one namespace per environment — and SSE/content-type metadata are not
    applicable (payloads are already AES-256-GCM ciphertext).
    """

    def __init__(self, base: str, account_id: str, namespace_id: str, token: str):
        self._values_url = (
            f"{base}/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values"
        )
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = httpx.Timeout(30.0, connect=10.0, read=60.0)

    def _url(self, key: str) -> str:
        return f"{self._values_url}/{quote(key, safe='')}"

    def put_object(self, Bucket=None, Key=None, Body=None, **kwargs) -> dict:  # noqa: N803
        body = Body if isinstance(Body, (bytes, bytearray)) else bytes(Body or b"")
        resp = httpx.put(self._url(Key), content=body, headers=self._headers, timeout=self._timeout)
        resp.raise_for_status()
        return {}

    def get_object(self, Bucket=None, Key=None, **kwargs) -> dict:  # noqa: N803
        resp = httpx.get(self._url(Key), headers=self._headers, timeout=self._timeout)
        if resp.status_code == 404:
            raise KeyError(Key)
        resp.raise_for_status()
        return {"Body": _KVBody(resp.content), "ContentLength": len(resp.content)}

    def delete_object(self, Bucket=None, Key=None, **kwargs) -> dict:  # noqa: N803
        resp = httpx.delete(self._url(Key), headers=self._headers, timeout=self._timeout)
        if resp.status_code != 404:
            resp.raise_for_status()
        return {}


def _kv_client() -> "_KVClient":
    with _lock:
        if "kv" not in _clients:
            _clients["kv"] = _KVClient(
                settings.cf_api_base,
                settings.cf_account_id,
                settings.kv_namespace_id,
                settings.cf_api_token,
            )
        return _clients["kv"]


def object_store_sse(key_id: str) -> dict:
    """SSE parameters for ``put_object``.

    AWS S3 encrypts each object with the KMS CMK. A Cloudflare backend manages
    encryption itself and rejects the ``aws:kms`` header, so return nothing
    there (payloads are already AES-256-GCM ciphertext regardless).
    """
    if settings.cloud_object_store:
        return {}
    return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": key_id}


def table(name: str):
    """Return a DynamoDB Table resource by logical name (see TABLES)."""
    return get_resource("dynamodb").Table(TABLES[name]["table"])


def stop_local_mock() -> None:
    global _mock, _resources_ready
    with _lock:
        _clients.clear()
        _resources.clear()
        if _mock is not None:
            _mock.stop()
            _mock = None
        _resources_ready = False


def ensure_resources() -> None:
    """Create DynamoDB tables, the private document bucket, and the KMS CMK."""
    global _resources_ready
    if _resources_ready:
        return
    with _lock:
        if _resources_ready:
            return
        ddb = get_client("dynamodb")
        existing = set()
        while True:
            resp = ddb.list_tables()
            existing.update(resp["TableNames"])
            if "LastTableName" not in resp or "NextTableName" not in resp:
                break
            break
        for spec in TABLES.values():
            if spec["table"] in existing:
                continue
            keys = {spec["key"][0], spec["key"][1]}
            for g in spec["gsis"]:
                keys.add(g["hash"])
                keys.add(g["range"])
            gsi_defs = [
                {
                    "IndexName": g["name"],
                    "KeySchema": [
                        {"AttributeName": g["hash"], "KeyType": "HASH"},
                        {"AttributeName": g["range"], "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for g in spec["gsis"]
            ]
            create_kwargs: dict = {
                "TableName": spec["table"],
                "KeySchema": [
                    {"AttributeName": spec["key"][0], "KeyType": "HASH"},
                    {"AttributeName": spec["key"][1], "KeyType": "RANGE"},
                ],
                "AttributeDefinitions": [
                    {"AttributeName": a, "AttributeType": "S"} for a in sorted(keys)
                ],
                "BillingMode": "PAY_PER_REQUEST",
                # Encryption at rest from day one.
                "SSESpecification": {"Enabled": True},
            }
            if gsi_defs:
                create_kwargs["GlobalSecondaryIndexes"] = gsi_defs
            ddb.create_table(**create_kwargs)
            try:
                # Point-in-time recovery is configured by a separate API.
                ddb.update_continuous_backups(
                    TableName=spec["table"],
                    PointInTimeRecoverySpecification={"PointInTimeRecoveryEnabled": True},
                )
            except Exception as exc:  # emulators may not model PITR
                print(f"[obsidian] PITR not enabled for {spec['table']}: {type(exc).__name__}")

        s3 = get_client("s3")
        if settings.kv_configured:
            # The Workers KV namespace is provisioned via the Cloudflare
            # dashboard or API and must already exist. Print (never raise) so a
            # missing namespace surfaces at first use, not at startup.
            print(f"[obsidian] object store: Cloudflare Workers KV namespace "
                  f"{settings.kv_namespace_id!r} (account {settings.cf_account_id})")
        elif settings.r2_configured:
            # The R2 bucket is provisioned in the Cloudflare dashboard and must
            # already exist; R2 also has no bucket-policy / public-access-block
            # API. Access is governed entirely by the R2 API token. Print (never
            # raise) so a missing bucket surfaces at first use, not at startup.
            print(f"[obsidian] object store: Cloudflare R2 bucket {settings.document_bucket!r} "
                  f"at {settings.r2_endpoint}")
        else:
            buckets = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
            if settings.document_bucket not in buckets:
                if settings.aws_region == "us-east-1":
                    s3.create_bucket(Bucket=settings.document_bucket)
                else:
                    s3.create_bucket(
                        Bucket=settings.document_bucket,
                        CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
                    )
                try:
                    # Block all public access at the account/bucket level.
                    s3.put_public_access_block(
                        Bucket=settings.document_bucket,
                        PublicAccessBlockConfiguration={
                            "BlockPublicAcls": True,
                            "IgnorePublicAcls": True,
                            "BlockPublicPolicy": True,
                            "RestrictPublicBuckets": True,
                        },
                    )
                except Exception as exc:
                    print(f"[obsidian] public access block not applied: {type(exc).__name__}")
                try:
                    s3.put_bucket_policy(
                        Bucket=settings.document_bucket,
                        policy=(
                            '{"Version":"2012-10-17","Statement":['
                            '{"Sid":"DenyInsecureTransport","Effect":"Deny","Principal":"*",'
                            '"Action":"s3:*","Resource":["arn:aws:s3:::%s","arn:aws:s3:::%s/*"],'
                            '"Condition":{"Bool":{"aws:SecureTransport":"false"}}},'
                            '{"Sid":"EnforceTLSVersion","Effect":"Deny","Principal":"*",'
                            '"Action":"s3:*","Resource":["arn:aws:s3:::%s","arn:aws:s3:::%s/*"],'
                            '"Condition":{"NumericLessThan":{"s3:TlsVersion":"1.2"}}}]}'
                            % (settings.document_bucket, settings.document_bucket,
                               settings.document_bucket, settings.document_bucket)
                        ),
                    )
                except Exception:
                    pass  # bucket policies are not supported by every emulator

        kms = get_client("kms")
        cfg = table("config")
        key_id = settings.kms_key_id
        if not key_id:
            item = cfg.get_item(Key={"pk": "CONFIG#kms_key", "sk": "META"}).get("Item")
            if item:
                key_id = item["key_id"]
            else:
                created = kms.create_key(
                    Description="OBSIDIAN document encryption CMK",
                    KeyUsage="ENCRYPT_DECRYPT",
                    Origin="AWS_KMS",
                )
                key_id = created["KeyMetadata"]["KeyId"]
                try:
                    # Automatic annual rotation of the CMK.
                    kms.enable_key_rotation(KeyId=key_id)
                except Exception as exc:
                    print(f"[obsidian] key rotation not enabled: {type(exc).__name__}")
                cfg.put_item(
                    Item={
                        "pk": "CONFIG#kms_key",
                        "sk": "META",
                        "key_id": key_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
        cfg.put_item(Item={"pk": "CONFIG#ready", "sk": "META", "value": "1"})
        _resources_ready = True


def kms_key_id() -> str:
    if persistence.enabled():
        return persistence.software_kms().key_id
    ensure_resources()
    if settings.kms_key_id:
        return settings.kms_key_id
    item = table("config").get_item(Key={"pk": "CONFIG#kms_key", "sk": "META"}).get("Item")
    if not item:
        raise RuntimeError("KMS key is not configured")
    return item["key_id"]
