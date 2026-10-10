"""AWS resource access.

All DynamoDB / S3 / KMS calls go through this module.

In local development (OBSIDIAN_LOCAL_AWS=true) the AWS SDK is intercepted by
moto, so the application code path is byte-for-byte the same one that runs
against real AWS. In production the same boto3 clients talk to real services.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key, Attr  # noqa: F401  (re-exported for handlers)

from .config import settings

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
            _mock = mock_aws()
            _mock.start()


def get_client(service: str):
    """Return a cached boto3 client. Moto intercepts calls when running locally."""
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
    ensure_resources()
    if settings.kms_key_id:
        return settings.kms_key_id
    item = table("config").get_item(Key={"pk": "CONFIG#kms_key", "sk": "META"}).get("Item")
    if not item:
        raise RuntimeError("KMS key is not configured")
    return item["key_id"]
