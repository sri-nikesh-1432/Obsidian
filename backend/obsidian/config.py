"""Environment-driven configuration.

Secrets are read from environment variables only. Nothing sensitive is
hardcoded and nothing sensitive is ever sent to the frontend.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    # Environment — fail closed: development affordances must be opted into
    # explicitly (local/server.py and tests/conftest.py both do so).
    env: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_ENV", "development"))
    local_aws: bool = field(default_factory=lambda: _bool("OBSIDIAN_LOCAL_AWS", False))
    dev_mode: bool = field(default_factory=lambda: _bool("OBSIDIAN_DEV_MODE", False))

    # AWS
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))
    table_prefix: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_TABLE_PREFIX", "obsidian"))
    document_bucket: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_DOCUMENT_BUCKET", "obsidian-documents-local"))
    kms_key_id: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_KMS_KEY_ID", ""))

    # Object storage backend. "s3" (default) uses AWS S3 — or moto in-process
    # when OBSIDIAN_LOCAL_AWS is set. Two Cloudflare backends are supported and
    # replace only the *object store*; document metadata still lives in DynamoDB
    # and the DEK is still wrapped by KMS:
    #   "r2" — Cloudflare R2 (S3-compatible; requires a payment method to
    #          enable even on the free tier).
    #   "kv" — Cloudflare Workers KV (S3 is not spoken; accessed over the
    #          Workers KV REST API, so it works on the cardless Workers Free
    #          plan). Values are capped at 25 MiB and reads are eventually
    #          consistent, so this suits small vaults.
    # Locally, moto keeps emulating DynamoDB/KMS while R2 requests pass through
    # to Cloudflare (aws._ensure_mock configures the passthrough).
    storage_backend: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_STORAGE_BACKEND", "s3").strip().lower())
    r2_endpoint: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_R2_ENDPOINT", "").strip())
    r2_access_key_id: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_R2_ACCESS_KEY_ID", ""))
    r2_secret_access_key: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_R2_SECRET_ACCESS_KEY", ""))
    r2_region: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_R2_REGION", "auto"))

    # Cloudflare Workers KV object store (storage_backend="kv").
    cf_api_base: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_CF_API_BASE", "https://api.cloudflare.com/client/v4").rstrip("/"))
    cf_account_id: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_CF_ACCOUNT_ID", ""))
    cf_api_token: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_CF_API_TOKEN", ""))
    kv_namespace_id: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_KV_NAMESPACE_ID", ""))

    # Durable state. When AWS is emulated in-process (moto) the database is
    # in-memory and resets on every restart. If a Cloudflare object store is
    # configured, the whole database is snapshotted there and restored on boot,
    # so users, documents, groups and keys survive restarts. Auto-enabled when a
    # Cloudflare credential is present; set OBSIDIAN_PERSIST_STATE=false to opt
    # out. The interval bounds how often a changed database is written back.
    persist_state: bool = field(default_factory=lambda: _bool(
        "OBSIDIAN_PERSIST_STATE",
        bool(os.environ.get("OBSIDIAN_CF_API_TOKEN") or os.environ.get("OBSIDIAN_R2_ACCESS_KEY_ID")),
    ))
    persist_interval: int = field(default_factory=lambda: _int("OBSIDIAN_PERSIST_INTERVAL", 20))

    # App
    public_base_url: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_PUBLIC_BASE_URL", "http://localhost:5173"))
    api_base_url: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_API_BASE_URL", "http://localhost:8080"))
    allowed_origins: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))
    cookie_name: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_COOKIE_NAME", "obsidian_session"))
    cookie_secure: bool = field(default_factory=lambda: _bool("OBSIDIAN_COOKIE_SECURE", False))

    # Auth
    session_ttl_seconds: int = field(default_factory=lambda: _int("OBSIDIAN_SESSION_TTL", 60 * 60 * 12))
    otp_ttl_seconds: int = field(default_factory=lambda: _int("OBSIDIAN_OTP_TTL", 300))
    otp_max_attempts: int = field(default_factory=lambda: _int("OBSIDIAN_OTP_MAX_ATTEMPTS", 5))
    resend_api_key: str = field(default_factory=lambda: os.environ.get("RESEND_API_KEY", ""))
    from_email: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_FROM_EMAIL", "OBSIDIAN <onboarding@resend.dev>"))
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))

    # Outbound email. Resend is used when RESEND_API_KEY is set; otherwise SMTP
    # (e.g. a Gmail app password) delivers real OTP mail; otherwise the local
    # dev mailbox is used. Credentials live in the environment / Secrets
    # Manager only and are never sent to the frontend.
    smtp_host: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _int("OBSIDIAN_SMTP_PORT", 587))
    smtp_username: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_SMTP_PASSWORD", ""))
    smtp_starttls: bool = field(default_factory=lambda: _bool("OBSIDIAN_SMTP_STARTTLS", True))

    # Payments — Razorpay (test or live). Secrets are server-side only; the
    # frontend only ever receives the publishable key id and an order id.
    razorpay_key_id: str = field(default_factory=lambda: os.environ.get("RAZORPAY_KEY_ID", ""))
    razorpay_key_secret: str = field(default_factory=lambda: os.environ.get("RAZORPAY_KEY_SECRET", ""))
    razorpay_webhook_secret: str = field(default_factory=lambda: os.environ.get("RAZORPAY_WEBHOOK_SECRET", ""))

    # Local dev / demo: scale up rate limits so seeding & smoke tests aren't
    # blocked by in-process counters. Never enabled in production.
    relax_rate_limits: bool = field(default_factory=lambda: _bool("OBSIDIAN_RELAX_RATE_LIMITS", False))

    # Uploads
    max_upload_mb: int = field(default_factory=lambda: _int("OBSIDIAN_MAX_UPLOAD_MB", 8))
    clamd_host: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_CLAMD_HOST", ""))
    clamd_port: int = field(default_factory=lambda: _int("OBSIDIAN_CLAMD_PORT", 3310))
    malware_fail_closed: bool = field(
        default_factory=lambda: _bool("OBSIDIAN_MALWARE_FAIL_CLOSED", True))

    # LLM provider — Ollama by default (local, no API key required).
    # Any OpenAI-compatible endpoint works: set LLM_PROVIDER=openai (or
    # "openai-compatible") plus LLM_BASE_URL, LLM_MODEL and LLM_API_KEY.
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "ollama"))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: os.environ.get(
        "LLM_BASE_URL", "http://localhost:11434/v1"))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "llama3.2"))
    embedding_model: str = field(default_factory=lambda: os.environ.get("EMBEDDING_MODEL", ""))
    retrieval_top_k: int = field(default_factory=lambda: _int("RETRIEVAL_TOP_K", 8))
    llm_timeout_seconds: int = field(default_factory=lambda: _int("LLM_TIMEOUT_SECONDS", 60))

    # Optional AWS Secrets Manager secret holding backend credentials.
    # JSON keys are the same names as the environment variables.
    secrets_name: str = field(default_factory=lambda: os.environ.get("OBSIDIAN_SECRET_NAME", ""))
    _secrets_loaded: bool = False

    _origins_override: list[str] | None = None

    def __post_init__(self) -> None:
        """Fail closed in production, whatever the environment claims."""
        if not self.is_prod:
            return
        disabled = []
        for attr, value in (("local_aws", False), ("dev_mode", False),
                            ("cookie_secure", True), ("relax_rate_limits", False)):
            if getattr(self, attr) != value:
                setattr(self, attr, value)
                disabled.append(attr)
        if disabled:
            print(f"[obsidian] production guard: forced {', '.join(disabled)} to their safe values",
                  file=__import__('sys').stderr)

    def load_secrets(self) -> None:
        """Resolve backend credentials from Secrets Manager when configured.

        Never raises and never logs values. Safe to call on every cold start.
        """
        if self._secrets_loaded:
            return
        self._secrets_loaded = True
        if not self.secrets_name:
            return
        try:
            import boto3
            client = boto3.client("secretsmanager", region_name=self.aws_region)
            resp = client.get_secret_value(SecretId=self.secrets_name)
            import json
            payload = json.loads(resp.get("SecretString") or "{}")
        except Exception as exc:  # noqa: BLE001 - report the failure, not the payload
            print(f"[obsidian] could not load secret {self.secrets_name!r}: {type(exc).__name__}",
                  file=__import__('sys').stderr)
            return
        key_map = {
            "RESEND_API_KEY": "resend_api_key",
            "GOOGLE_CLIENT_ID": "google_client_id",
            "GOOGLE_CLIENT_SECRET": "google_client_secret",
            "LLM_API_KEY": "llm_api_key",
            "RAZORPAY_KEY_ID": "razorpay_key_id",
            "RAZORPAY_KEY_SECRET": "razorpay_key_secret",
            "RAZORPAY_WEBHOOK_SECRET": "razorpay_webhook_secret",
            "OBSIDIAN_SMTP_PASSWORD": "smtp_password",
            "SMTP_PASSWORD": "smtp_password",
        }
        for key, attr in key_map.items():
            value = payload.get(key)
            if isinstance(value, str) and value:
                setattr(self, attr, value)

    @property
    def origins(self) -> list[str]:
        if self._origins_override is not None:
            return self._origins_override
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @origins.setter
    def origins(self, value: list[str]) -> None:
        self._origins_override = value

    _is_prod_override: bool = False

    @property
    def is_prod(self) -> bool:
        return self.env == "production" or self._is_prod_override

    @is_prod.setter
    def is_prod(self, value: bool) -> None:
        self._is_prod_override = value

    @property
    def r2_configured(self) -> bool:
        """True when the object store is Cloudflare R2 and fully credentialed."""
        return (
            self.storage_backend == "r2"
            and bool(self.r2_endpoint)
            and bool(self.r2_access_key_id)
            and bool(self.r2_secret_access_key)
        )

    @property
    def kv_configured(self) -> bool:
        """True when the object store is Cloudflare Workers KV and credentialed."""
        return (
            self.storage_backend in ("kv", "workers-kv", "workers_kv")
            and bool(self.cf_account_id)
            and bool(self.cf_api_token)
            and bool(self.kv_namespace_id)
        )

    @property
    def cloud_object_store(self) -> bool:
        """True when objects live in a Cloudflare store (R2 or Workers KV)."""
        return self.r2_configured or self.kv_configured

    @property
    def state_persistence_enabled(self) -> bool:
        """True when in-process AWS state should be mirrored to Cloudflare.

        Only meaningful for the in-memory (moto) deployment with a Cloudflare
        object store to write into; real AWS is already durable.
        """
        return self.persist_state and self.local_aws and self.cloud_object_store

    @property
    def llm_configured(self) -> bool:
        """True when a generation provider is usable as configured."""
        if self.llm_provider.strip().lower() in ("ollama", "local", "none"):
            return bool(self.llm_base_url) and self.llm_provider.strip().lower() != "none"
        return bool(self.llm_api_key) and bool(self.llm_base_url)


settings = Settings()
