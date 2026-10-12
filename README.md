# OBSIDIAN

A secure student document vault. Students upload, encrypt, and share
documents; faculty verify students and run **groups** (a cohort or class they
can message all at once — a built-in group chat); recruiters view consented
profiles; admins see analytics and audit trails. A personal, consent-gated AI
assistant (**OBSIDIAN Intelligence**) answers questions grounded in a user's
own documents and profile.

- **Backend** — Python "Lambda" handlers (`backend/obsidian/`) that run
  unchanged on AWS API Gateway + Lambda. Locally, AWS (DynamoDB, S3, KMS) is
  emulated **in-process by moto**, so no AWS account or Docker is needed.
- **Frontend** — Vite + React + TypeScript + Tailwind.

### Encryption, storage & access at a glance

| Concern | What OBSIDIAN uses |
| ------- | ------------------ |
| Document encryption | **AES-256-GCM** (authenticated) with a fresh 256-bit key per upload |
| Key management | **AWS KMS envelope encryption** — a CMK wraps each per-document DEK; keys never leave the backend |
| Object storage | Pluggable: **AWS S3** (default), **Cloudflare R2**, or **Cloudflare Workers KV** — see *Storage* below |
| Metadata | **DynamoDB** (encrypted at rest, point-in-time recovery) |
| Access control | Server-side sessions + per-route **RBAC** (`student` / `faculty` / `recruiter` / `admin`); authorization is enforced on the server, never trusted from the client |
| Secrets | Secrets are **backend-only**; the browser receives only a publishable payment key id. No secret is ever bundled into the frontend |

See [Security & encryption](#security--encryption) below for the full model.

---

## Run it locally (preview)

Open **three terminals**.

### 1. Backend API (port 5000)

```bash
cd backend
pip install -r requirements.txt
# Point at a local model for full conversational answers (optional):
LLM_PROVIDER=ollama LLM_MODEL=llama3.2:3b python local/server.py   # http://127.0.0.1:5000
```

Set `LLM_MODEL` to a model you have pulled (`ollama list`). Without a model the
app still runs — Intelligence just reports that no model is configured instead
of pretending retrieval is an answer.

### 2. Seed demo data (once, while the backend is running)

```bash
cd backend
python local/seed.py http://127.0.0.1:5000
```

### 3. Frontend (port 5173)

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Open <http://localhost:5173>. The Vite dev server proxies `/api` to the backend
on port 5000 (same-origin cookies). Only `/api` is proxied: the public share
pages live at `/s/:token` and are served by the SPA. To point at a different
backend, set `VITE_API_TARGET`.

---

## Demo accounts

Password for all accounts: **`correct-horse-battery`**

| Role      | Email                     |
| --------- | ------------------------- |
| Student   | `arjun@obsidian.dev`      |
| Student   | `meera@obsidian.dev`      |
| Faculty   | `prof.rao@obsidian.dev`   |
| Recruiter | `talent@northwind.io`     |
| Admin     | `admin@obsidian.dev`      |

Sign-in uses an **email one-time code (OTP)**. In dev mode the code is returned
by the API and surfaced in the UI, so no email is sent. Choose the role that
matches the account at sign-in.

---

## Role-based onboarding

Each account completes a **role-specific** form, driven by the server-verified
role (never a client-supplied one). The field definitions live in
`backend/obsidian/profile_schema.py` (backend truth) and
`frontend/src/lib/roleProfile.ts` (UI mirror).

| Role      | Onboarding fields |
| --------- | ----------------- |
| Student   | name, phone, institution, course, education level, department, year, graduation year, CGPA, skills, bio, profile visibility |
| Faculty   | name, institution, faculty/employee ID, department, designation, areas of expertise, office contact, bio |
| Recruiter | name, company, job title, industry, company website, hiring domains, contact number |
| Admin     | name, admin/operations designation, organization |

A role can only set the fields belonging to it — a faculty account sending
`cgpa` gets `422`, and never receives student fields back. **Admin accounts
cannot be self-registered in production**; they are provisioned through a
trusted authorization path.

---

## Sign in with Google (every role, sign-in and sign-up)

One Google OAuth client powers **all four roles** on **both** the sign-in and
sign-up surfaces, and from the landing page — one flow, selected by a role
picker rather than a button per role.

```
frontend (landing · /login · /signup)        backend  obsidian.functions.auth
  │ GET /api/v1/auth/google/start?role=X  ──▶  validate role, mint single-use
  │                                            state, stash {role} in DynamoDB
  │ ◀── { url: https://accounts.google.com/… }   (client secret stays server-side)
  │ window.location.href = url                 (full-page redirect)
  ▼
accounts.google.com ──▶ GET {PUBLIC}/api/v1/auth/google/callback?code&state
                                                    │ verify state (TTL, one-shot)
                                                    │ exchange code → verify id_token
                                                    │ (aud, iss, exp, email_verified)
                                                    ▼
                                       existing email → sign in
                                       new email      → create with stashed role
                                                        + role profile + audit event
                                                    │ set session cookie
                                                    ▼
                                         302 → {PUBLIC}/auth/complete
```

- **Endpoints** — `GET /api/v1/auth/google/start?role=<student|faculty|recruiter|admin>`
  and `GET /api/v1/auth/google/callback`.
- **Role handling** — the role is sent to `start` and stashed server-side with a
  single-use `state`; the callback trusts only that, never a client-supplied role.
- **Sign-in vs sign-up** — one flow: an existing email signs in, a new email is
  created with the chosen role and a role-specific profile row. Wired for every
  role on `/login`, `/signup` and the landing page (`GoogleAuthButton`).
- **Admin** — Google signs in an *existing* admin; a **new** admin account is not
  self-registered in production (dev mode allows it), matching the OTP path.
- **Where the client lives** — `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` come
  from the environment or from AWS Secrets Manager via `OBSIDIAN_SECRET_NAME`.
  The browser only ever receives the authorization URL.

**Register these on the OAuth client** (Google Cloud console → APIs & Services →
Credentials), character for character:

| Field | Local development | Deployed |
| ----- | ----------------- | -------- |
| Authorized JavaScript origin | `http://localhost:5173` | your `PublicBaseUrl` |
| Authorized redirect URI | `http://localhost:5173/api/v1/auth/google/callback` | `${PublicBaseUrl}/api/v1/auth/google/callback` |

In dev the redirect goes through the Vite proxy so it is same-origin (cookies
behave as in production). Open the app at `http://localhost:5173` — **not**
`127.0.0.1` — or the origin won't match. After deployment, the `GoogleRedirectUri`
stack output prints the exact value to register.

---

## Tests

```bash
# Unit / integration suite (no server needed)
cd backend && python -m pytest tests/          # 76 tests

# End-to-end smoke against a running stack
python tests/e2e_smoke.py http://localhost:5173   # 27 checks
```

---

## Security & encryption

- **Authenticated encryption per document.** Every upload generates a fresh
  256-bit data encryption key; the file is encrypted with **AES-256-GCM**, so
  tampering is detected on read. Only ciphertext ever reaches the object store.
- **Envelope key management.** The per-document DEK is wrapped by an **AWS KMS**
  customer master key (automatic rotation). Keys never leave the backend, never
  appear in API responses, never enter vector storage, and never touch a model
  prompt. Key versions are retained for rotation.
- **Encrypted at rest and in transit.** DynamoDB tables use SSE-KMS with
  point-in-time recovery; the S3 bucket is private (all public access blocked),
  TLS-only, versioned, and SSE-KMS encrypted. Cloudflare R2 / Workers KV manage
  their own at-rest encryption (payloads are already ciphertext).
- **Server-side authorization.** Sessions are server-side and revocable; role
  checks run on the server for every route (`student` / `faculty` / `recruiter`
  / `admin`), and the client can never widen its own permissions. Mutations are
  origin-checked (CSRF defence) and rate-limited.
- **Audit trail.** Sign-ins, MFA, uploads, downloads, shares, lookups, group
  actions and security events are recorded with request correlation IDs.
  Passwords, OTPs, keys, and raw share tokens are never written to logs.
- **Secrets stay server-side.** Provider secrets (KMS, Cloudflare, Razorpay,
  SMTP, Google OAuth) live only in backend environment variables. The frontend
  ships **no secrets** — the browser receives only the Razorpay *publishable*
  key id, and all sensitive calls go through the same-origin API.

## Durable state (survives restarts)

The Docker/VM deployment runs AWS **in-process** (moto), so DynamoDB, S3 and KMS
are in memory — normally that means a restart wipes every account and document.
When a Cloudflare object store is configured (Workers KV or R2), OBSIDIAN turns
that on its head: the entire database is snapshotted into the object store and
restored on boot, so **users, documents, groups, sessions and encryption keys
all survive a restart or redeploy**.

- A background writer mirrors every DynamoDB table to a single gzipped blob
  (`system/db-snapshot.json.gz`) at most every `OBSIDIAN_PERSIST_INTERVAL`
  seconds (default 20), and flushes immediately on shutdown (SIGTERM).
- On startup the snapshot is read back into the fresh in-memory database
  before the first request is served.
- The KMS CMK is replaced by a small **software KMS** whose root key lives in
  the same object store (`system/kms-root`), so previously wrapped document
  keys stay decryptable after a restart — the real KMS key material is not
  exportable, which is why this shim exists for the emulated deployment.
- Auto-enabled whenever `OBSIDIAN_CF_API_TOKEN` (or R2 credentials) are
  present; set `OBSIDIAN_PERSIST_STATE=false` to opt out. It is a no-op against
  real AWS, which is already durable.

**Trade-off:** the write-back is bounded by `OBSIDIAN_PERSIST_INTERVAL`, so a
hard crash (not a clean restart) can lose the last few seconds of changes, and
Workers KV's free tier allows 1,000 writes/day. For strong durability use real
AWS (`infra/template.yaml`) or R2; for a cardless demo, Workers KV is enough.

## Groups & group chat (faculty)

A `faculty` account is a *teacher*. Teachers create groups, add students by
their opaque student code, and post messages every member sees — a lightweight
classroom feed.

| Endpoint | Who | Purpose |
| -------- | --- | ------- |
| `POST /groups` | faculty | Create a group (name + optional description) |
| `GET /groups` | faculty & student | List groups (teachers: the ones they own; students: the ones they belong to) |
| `GET /groups/{id}` | owner & members | Group details, roster, and recent messages |
| `PATCH /groups/{id}` | owner | Rename / edit the description |
| `DELETE /groups/{id}` | owner | Delete the group, roster, and messages |
| `POST /groups/{id}/members` | owner | Add a student by their `OBS-…` code |
| `DELETE /groups/{id}/members/{student_id}` | owner | Remove a student |
| `POST /groups/{id}/messages` | owner & members | Post a message to the group chat |
| `GET /groups/{id}/messages` | owner & members | Read the group chat |

Access is denied with a generic `404` to anyone who is neither the owner nor a
member, so group existence is never leaked. Only the owner can manage the
roster; any member (the teacher included) can post. Every group action is
audited. Groups live in their own DynamoDB table (`obsidian-groups`) keyed so
that a teacher's groups, a student's memberships, and each group's message
timeline are all single-query reads.

## Storage & payments (students)

Every student account starts with **5 GB free**. Uploading is refused with
`402 STORAGE_QUOTA_EXCEEDED` once the entitlement is full. Paid plans *add*
10 GB permanently:

| Plan | Total storage | Price (one-time, INR) |
| ---- | ------------- | --------------------- |
| Free | 5 GB | — |
| Plan 1 | 15 GB | **₹3,999** |
| Plan 2 | 25 GB | **₹6,999** |
| Plan 3 | 35 GB | **₹6,999** |
| … | +10 GB each | **₹6,999** |

The ladder is defined once, server-side, in `backend/obsidian/plans.py`. The
client can never choose a price or skip a step.

### Payment flow (Razorpay)

```
POST /api/v1/billing/orders   -> server creates the Razorpay order (price fixed server-side)
Razorpay Checkout             -> user pays
POST /api/v1/billing/verify   -> server checks HMAC(order_id|payment_id) with the key secret
POST /api/v1/billing/webhook  -> optional out-of-band confirmation (webhook secret)
```

Only a passing signature check credits storage, and crediting is idempotent —
a replayed or duplicated confirmation never adds space twice. The key secret
never leaves the backend; the browser receives only the publishable key id.

| Endpoint | Who | Purpose |
| -------- | --- | ------- |
| `GET /billing/plans` | public | The plan ladder |
| `GET /billing/status` | student | Used / entitlement / next plan |
| `POST /billing/orders` | student | Create an order for the next plan |
| `POST /billing/verify` | student | Confirm a Checkout payment (signature checked) |
| `POST /billing/webhook` | public (signed) | Razorpay webhook confirmation |
| `GET /billing/history` | student | Purchase history |

`GET /auth/me` and `GET /documents` also carry a `storage` block, so the meter
in the sidebar and the vault renders without an extra round-trip.

### Cloudflare R2 object storage (optional)

Document bodies are stored through one abstraction (`aws.storage_client()`), so
the object store can be redirected to **Cloudflare R2** purely by configuration
— no AWS S3 account required. Metadata still lives in DynamoDB and each DEK is
still wrapped by KMS; R2 replaces only the ciphertext bucket, which already
holds AES-256-GCM ciphertext, so no `aws:kms` SSE header is sent to R2.

| Variable | Example | Notes |
| -------- | ------- | ----- |
| `OBSIDIAN_STORAGE_BACKEND` | `r2` | `s3` (default) or `r2` |
| `OBSIDIAN_R2_ENDPOINT` | `https://<account>.r2.cloudflarestorage.com` | From the R2 dashboard |
| `OBSIDIAN_R2_ACCESS_KEY_ID` | *(secret)* | R2 **S3** key id |
| `OBSIDIAN_R2_SECRET_ACCESS_KEY` | *(secret)* | R2 **S3** secret |
| `OBSIDIAN_R2_REGION` | `auto` | R2 uses `auto` |
| `OBSIDIAN_DOCUMENT_BUCKET` | `obsidian-documents` | Must be an **existing** R2 bucket |

Create the credentials under **R2 → Manage R2 API Tokens → Create API Token →
Object Read & Write** — this yields an S3 access key id / secret pair. (A
Cloudflare *account* API token is a different thing and does not work here.)
Because R2 has no create-bucket or bucket-policy API, create the bucket first
and scope the token to it. Locally, moto keeps emulating DynamoDB/KMS while R2
requests pass through to Cloudflare.

> **Note:** R2 requires a payment method to activate, even on the free tier
> (10 GB-month). If you need a cardless option, use Workers KV below.

### Cloudflare Workers KV object storage (optional, cardless)

Workers KV is available on the Workers **Free** plan without a payment method,
so it is the alternative when R2 cannot be enabled. It is **not S3-compatible**;
the app talks to the KV REST API through a small boto3-shaped shim, so the
document code is unchanged. Only the object store is replaced — metadata stays
in DynamoDB and DEKs stay KMS-wrapped.

| Variable | Example | Notes |
| -------- | ------- | ----- |
| `OBSIDIAN_STORAGE_BACKEND` | `kv` | `kv` selects Workers KV |
| `OBSIDIAN_CF_ACCOUNT_ID` | `eb221…225` | Cloudflare account id |
| `OBSIDIAN_CF_API_TOKEN` | *(secret)* | Token with **Workers KV Storage: Edit** |
| `OBSIDIAN_KV_NAMESPACE_ID` | *(id)* | Existing KV namespace id |
| `OBSIDIAN_CF_API_BASE` | `https://api.cloudflare.com/client/v4` | Override for tests |

Create the namespace in **Workers & Pages → KV** (or `POST /accounts/{id}/storage/kv/namespaces`
with `{"title": "obsidian-documents"}`), then create an account API token that
grants **Workers KV Storage: Edit**. Free-tier limits: 1 GB storage, 25 MiB per
value, 1,000 writes/day, 100k reads/day, and reads are **eventually consistent**
(a just-uploaded file may 404 for up to ~60s). Suitable for small vaults; R2 is
preferred when a payment method is available.

---


## Deploy (Docker · AWS · Netlify · Google)

See **[docs/DEPLOY.md](docs/DEPLOY.md)**. The short version:

```bash
docker compose up --build     # full app on http://localhost:8080 — NO cloud
                              # credentials of any kind required
```

The Docker image serves the built SPA and the API from one process; DynamoDB,
S3 and KMS are served in-process by moto, so the *same* handlers that deploy to
Lambda run unchanged and no AWS account is needed. Google sign-in, SMTP email
and Razorpay are switched on purely by environment variables.

---

## Deploy to AWS (S3 · KMS · DynamoDB · API Gateway · Lambda)

`infra/template.yaml` is a SAM template provisioning the whole serverless
boundary. The same handlers in `backend/obsidian/` run unchanged on Lambda
(`OBSIDIAN_LOCAL_AWS=false`, so real AWS is used).

| Piece | Resource | Purpose |
| ----- | -------- | ------- |
| **Lambda** | `GatewayFunction` — `obsidian.gateway.dispatch` | One function serves every `/api/v1` route; X-Ray tracing on. |
| **API Gateway** | `HttpApi` (HTTP API v2, stage `v1`) | Routes `/` and `/{proxy+}` to the Lambda; 100 burst / 50 rps throttle; JSON access logs. |
| **DynamoDB** | 14 tables — `obsidian-users`, `-profiles`, `-sessions`, `-mfa`, `-documents`, `-shares`, `-connections`, `-groups`, `-audit`, `-rag`, `-config`, `-ratelimits`, `-devmail`, `-billing` | Pay-per-request, SSE-KMS, PITR; `ratelimits` has TTL. |
| **S3** | `DocumentBucket` | Private (all public access blocked), SSE-KMS with the CMK, versioned, STANDARD_IA at 30 days, TLS-only bucket policy. Holds ciphertext only. |
| **KMS** | `KmsKey` | CMK with automatic rotation; wraps per-document data keys. Key policy delegates to the account root to avoid a CFN dependency cycle. |
| **Secrets Manager** | `SecretsManagerSecret` | JSON credentials (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RESEND_API_KEY`, `OBSIDIAN_SMTP_PASSWORD`, `LLM_API_KEY`), loaded at cold start via `OBSIDIAN_SECRET_NAME`. |
| **CloudWatch** | log groups + `5xx` / `429` alarms | 30-day retention (configurable). |

### Build & deploy

```bash
cd infra
sam build                 # pip-only packaging (x86_64) — no Docker needed
sam validate --lint       # template + cfn-lint
sam deploy --guided       # first run; afterwards: sam deploy
```

Key parameters (`--parameter-overrides`):

| Parameter | Default | Notes |
| --------- | ------- | ----- |
| `PublicBaseUrl` | `http://localhost:5173` | **Set to your CloudFront / custom domain.** Drives the OAuth redirect, post-login redirect and CORS. |
| `GoogleClientId` | *(empty)* | Required for Google sign-in (a public identifier). |
| `GoogleClientSecret` | *(empty)* `NoEcho` | Required for Google sign-in. Never committed — pass at deploy time. |
| `RazorpayKeyId` | test key id | Publishable — also sent to the browser. |
| `RazorpayKeySecret` | *(empty)* `NoEcho` | **Required for real payments.** Server-side only. |
| `RazorpayWebhookSecret` | *(empty)* `NoEcho` | Secret configured on the Razorpay webhook endpoint. |
| `Environment` | `production` | `production` forces fail-closed defaults (secure cookies, no dev mode). |
| `DocumentBucketName` | `obsidian-docs` | Must be globally unique. |

Credentials are **never given defaults in source** — every secret parameter
(Google, Razorpay) defaults to empty and must be supplied via
`--parameter-overrides` or Secrets Manager, so the repository contains no
secrets and is safe to push.

`sam build` packages the `obsidian` package plus its dependencies (boto3,
argon2, cffi, google-auth…). Deploying needs **real AWS credentials** — Google
OAuth credentials authenticate the *user*, not the AWS API.

### What the Lambda is given

`OBSIDIAN_LOCAL_AWS=false`, `OBSIDIAN_DEV_MODE=false`, `OBSIDIAN_COOKIE_SECURE=true`,
`OBSIDIAN_TABLE_PREFIX=obsidian`, the bucket and KMS key IDs, and
`OBSIDIAN_SECRET_NAME`. `OBSIDIAN_PUBLIC_BASE_URL=PublicBaseUrl`,
`OBSIDIAN_API_BASE_URL=${PublicBaseUrl}/api/v1`, and
`OBSIDIAN_ALLOWED_ORIGINS=PublicBaseUrl`, so the OAuth redirect and CORS point at
the deployed origin rather than localhost. IAM grants least-privilege access to
just those tables, the bucket, the key, and the one secret.

---

## Your part — credentials for full functionality / deploy

Local preview works with none of these. Supply them to enable the features
below (export them into the backend's environment; a `.env` file is not read
automatically).

| Feature | Variables | Where to get it |
| ------- | --------- | --------------- |
| Email OTP delivery (API) | `RESEND_API_KEY`, `OBSIDIAN_FROM_EMAIL` | https://resend.com/api-keys |
| Email OTP delivery (SMTP) | `OBSIDIAN_SMTP_HOST`, `OBSIDIAN_SMTP_PORT`, `OBSIDIAN_SMTP_USERNAME`, `OBSIDIAN_SMTP_PASSWORD` | Any SMTP relay — a Gmail app password works |
| Storage payments | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | https://dashboard.razorpay.com/app/keys |
| "Sign in with Google" (all roles) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google Cloud console — see *Sign in with Google* |
| AI answers (default) | `LLM_PROVIDER=ollama`, `LLM_MODEL=<pulled model>` | Local [Ollama](https://ollama.com) — `ollama pull llama3.2` |
| AI answers (hosted) | `LLM_PROVIDER=openai`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | Any OpenAI-compatible provider |
| Deploy to real AWS | AWS creds; then `infra/template.yaml` parameters | See *Deploy to AWS* — provisions S3, KMS, DynamoDB, API Gateway, Lambda, Secrets Manager |

Until an email channel is configured (`RESEND_API_KEY`, or `OBSIDIAN_SMTP_HOST`),
the app runs in **dev mode**: OTPs appear in the UI instead of being emailed.
Delivery order is Resend → SMTP → local dev mailbox.

### Environment reference

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `OBSIDIAN_ENV` | `development` | Set to `production` to lock down dev behaviour |
| `OBSIDIAN_LOCAL_AWS` | `true` | Use in-process moto instead of real AWS |
| `OBSIDIAN_DEV_MODE` | `true` | Surface OTPs / dev affordances |
| `OBSIDIAN_RELAX_RATE_LIMITS` | `false` (dev server sets `1`) | Scale up rate limits for seeding/tests |
| `OBSIDIAN_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | CORS allow-list |
| `OBSIDIAN_COOKIE_SECURE` | `false` | Set `true` behind HTTPS |
| `OBSIDIAN_STATIC_DIR` | *(empty)* | Serve the built SPA from the API process (single-container deploy) |
| `OBSIDIAN_STORAGE_BACKEND` | `s3` | `s3` (AWS S3 / moto), `r2` (Cloudflare R2), or `kv` (Cloudflare Workers KV — see above) |
| `OBSIDIAN_R2_ENDPOINT` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` / `_REGION` | *(empty)* / `auto` | Cloudflare R2 S3 credentials and endpoint |
| `OBSIDIAN_CF_ACCOUNT_ID` / `OBSIDIAN_CF_API_TOKEN` / `OBSIDIAN_KV_NAMESPACE_ID` | *(empty)* | Cloudflare Workers KV object store (cardless) |
| `OBSIDIAN_SMTP_HOST` / `_PORT` / `_USERNAME` / `_PASSWORD` | *(empty)* / `587` | SMTP delivery for real OTP email |
| `RAZORPAY_KEY_ID` / `_KEY_SECRET` / `_WEBHOOK_SECRET` | *(empty)* | Storage payments. Unset ⇒ simulated checkout in dev mode only |
| `LLM_PROVIDER` | `ollama` | `ollama` or any OpenAI-compatible provider |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Model endpoint (OpenAI-compatible path) |
| `LLM_MODEL` | `llama3.2` | Must be a model the provider has |
| `LLM_API_KEY` | *(empty)* | Required for hosted providers; unused by Ollama |
| `EMBEDDING_MODEL` | *(empty)* | Reserved for provider embeddings |
| `RETRIEVAL_TOP_K` | `8` | Passages passed to the model per question |
| `LLM_TIMEOUT_SECONDS` | `60` | Generation timeout |

---

## How OBSIDIAN Intelligence answers

```
question → isolate to the user's own partition → hybrid retrieval
(profile + document chunks) → LLM writes a grounded answer → cited sources
```

- **Isolation** is enforced server-side: the RAG identity comes from the
  session, never from a request parameter. Retrieval only ever queries
  `RAG#<user_id>`.
- **Retrieval** is hybrid (vector similarity + lexical overlap) over the user's
  own profile and eligible documents, with page numbers tracked for citations.
- **Generation** is done by the configured model. Retrieval supplies evidence;
  it is never returned as the answer. With no model configured the API returns
  an explicit notice rather than raw fragments.
- **Conversation memory**: the client sends recent turns; follow-ups such as
  "which project did I work on *there*" resolve against prior context.
- **Citations**: each answer lists the source documents (and page numbers where
  available). The profile summary is used as context but is not cited as a file.
- **Consent**: nothing is indexed until the user opts in; opting out deletes
  every vector in their partition. The vault works fully without AI.

---

## Project layout

```
backend/
  obsidian/          Lambda handlers + shared runtime
    gateway.py       request pipeline (auth -> role -> authorize -> audit)
    router.py        route table and {param} matching
    profile_schema.py role profile fields (single source of truth)
    rag.py           ingestion, per-user retrieval, conversational answers
    functions/       auth, documents, sharing, connections, groups, profile, intelligence, admin, billing ...
    plans.py         student storage plan ladder (5 GB free, +10 GB tiers)
    aws.py           moto bootstrap + cached boto3 clients
    persistence.py   durable snapshot/restore + software KMS for the emulated deploy
    crypto.py        AES-256-GCM envelope encryption
  local/
    server.py        local API Gateway-compatible dev server (port 5000)
    seed.py          demo data seeder (drives the real API)
  tests/             pytest suite
frontend/
  src/pages/Groups.tsx           faculty groups + group chat (shared by teacher & student)
  src/components/StorageMeter.tsx  quota meter (sidebar + vault)
  src/pages/student/Billing.tsx    plans + Razorpay Checkout + history
  src/lib/razorpay.ts      Checkout helper
  src/lib/roleProfile.ts   role-specific profile field definitions
  src/components/Markdown.tsx  lightweight answer renderer
  src/pages/student/Intelligence.tsx  conversational assistant UI
tests/e2e_smoke.py   end-to-end smoke against the running stack
Dockerfile            single-container deploy (frontend + API, no cloud creds)
docker-compose.yml    one-command deploy
netlify.toml          static frontend deploy
infra/template.yaml   AWS SAM stack (S3 · KMS · DynamoDB · API Gateway · Lambda)
docs/DEPLOY.md        deploy guide for every target
```

## Known gaps

- Embeddings are deterministic feature-hashing (offline, no external service).
  `EMBEDDING_MODEL` is reserved for wiring real provider embeddings.
- Faculty/recruiter *verification* is not yet an approval workflow — accounts
  are trusted on creation. Only admin self-registration is hard-blocked.
- Assistant responses are not streamed yet (answers arrive complete).
- Storage upgrades are one-time purchases, not auto-renewing subscriptions; a
  Razorpay subscription plan would be the next step.
- The Docker deployment runs AWS in-process (moto), so its data is in memory by
  default. Configure a Cloudflare object store (see *Durable state*) to snapshot
  and restore it across restarts, or use the AWS stack for real durability. The
  snapshot is interval-based, so a hard crash can lose the last few seconds.
- Every later +10 GB tier is priced at ₹6,999 (the specification gives explicit
  prices for the 15 GB and 25 GB plans only).
