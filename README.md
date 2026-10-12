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
| Object storage | Pluggable: **AWS S3** (default), **Cloudflare Workers KV** — see *Storage* below |
| Metadata | **DynamoDB** (encrypted at rest, point-in-time recovery) |
| Access control | Server-side sessions + per-route **RBAC** (`student` / `faculty` / `recruiter` / `admin`); authorization is enforced on the server, never trusted from the client |
| Secrets | Secrets are **backend-only**; the browser receives only a publishable payment key id. No secret is ever bundled into the frontend |

See [Security & encryption](#security--encryption) below for the full model.


LLM PROVIDER = ollama LLM_MODEL = llama3.2:3b 


Sign-in uses an **email one-time code (OTP)**. used RESEND API for generating OTP's to send to mail.

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
| Admin     | *(none — administrators skip onboarding entirely)* |

A role can only set the fields belonging to it — a faculty account sending
`cgpa` gets `422`, and never receives student fields back.

**Administrators never see the onboarding wizard.** An admin account is created
with `onboarding_complete = true`, and both the API and the client route guards
send an admin straight to `/app/admin`.

### Who can be an admin

Admin access is gated by an **email allowlist** (`OBSIDIAN_ADMIN_EMAILS`,
comma-separated; default `srinikeshchinta@gmail.com`). This applies in every
environment and on every path — OTP registration, Google sign-up and
sign-in:

- registering as `admin` is rejected (`403`) unless the address is listed;
- an existing admin whose address is no longer listed **cannot sign in**;
- non-admins can never widen their own role.

Set `OBSIDIAN_ADMIN_EMAILS` to a comma-separated list to nominate more admins,
or to `*` to allow any address (the test suite uses `*`).

---

## Sign in with Google (every role, sign-in and sign-up)

One Google OAuth client powers **all four roles** on **both** the sign-in and
sign-up surfaces, and from the landing page — one flow, selected by a role
picker rather than a button per role.

- **Role handling** — the role is sent to `start` and stashed server-side with a
  single-use `state`; the callback trusts only that, never a client-supplied role.
- **Sign-in vs sign-up** — one flow: an existing email signs in, a new email is
  created with the chosen role and a role-specific profile row. Wired for every
  role on `/login`, `/signup` and the landing page (`GoogleAuthButton`).
- **Admin** — only an address on `OBSIDIAN_ADMIN_EMAILS` may be created as, or
  signed in as, an admin; any other admin request is rejected, matching the OTP path.
- **Where the client lives** — `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` come
  from the environment or from AWS Secrets Manager via `OBSIDIAN_SECRET_NAME`.
  The browser only ever receives the authorization URL.

**Register these on the OAuth client** (Google Cloud console → APIs & Services →
Credentials)

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

**This is the fix for "why do I get signed out when I refresh?"** The Render
free tier restarts (and sleeps) the container, which wipes the in-memory
database — taking every account and session with it, so *all* signed-in users
drop at once. Enabling durable state means the snapshot is restored on the next
boot, so sessions and accounts survive.

The Docker image already bakes in the Workers-KV backend, the account id, the
namespace id and `OBSIDIAN_PERSIST_STATE=true`. The **only** value left to
provide is the secret:

> Render → your service → **Environment** → add `OBSIDIAN_CF_API_TOKEN`
> (a Cloudflare token with **Workers KV Storage: Edit**). Save; Render redeploys
> and `/health` flips from `"durable_state": false` to `true`.

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

Only a passing signature check credits storage, and crediting is idempotent —
a replayed or duplicated confirmation never adds space twice. The key secret
never leaves the backend; the browser receives only the publishable key id.

### Cloudflare R2 object storage

Document bodies are stored through one abstraction (`aws.storage_client()`), so
the object store can be redirected to **Cloudflare R2** purely by configuration
— no AWS S3 account required. Metadata still lives in DynamoDB and each DEK is
still wrapped by KMS; R2 replaces only the ciphertext bucket, which already
holds AES-256-GCM ciphertext, so no `aws:kms` SSE header is sent to R2.

### Cloudflare Workers KV object storage (cardless)

Workers KV is available on the Workers **Free** plan without a payment method,
so it is the alternative when R2 cannot be enabled. It is **not S3-compatible**;
the app talks to the KV REST API through a small boto3-shaped shim, so the
document code is unchanged. Only the object store is replaced — metadata stays
in DynamoDB and DEKs stay KMS-wrapped.

## Deploy (Docker · AWS · Netlify · Google)

The Docker image serves the built SPA and the API from one process; DynamoDB,
S3 and KMS are served in-process by moto, so the *same* handlers that deploy to
Lambda run unchanged and no AWS account is needed. Google sign-in, SMTP email
and Razorpay are switched on purely by environment variables.

### Live deployment (Render + Netlify)

The public demo runs the API on **Render** (one container, in-process AWS) and
the SPA on **Netlify**, which proxies `/api/v1/*` to Render so the browser stays
same-origin (`netlify.toml`). `render.yaml` declares the service and its
environment; the one secret is entered in the dashboard, never committed.

| URL |
| `https://obsidiancloud.netlify.app` 
| `https://obsidian-abax.onrender.com` 



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

## Administration console (admin only)

The UI renders **pie/donut charts and 14-day bar charts** with inline SVG (no
charting dependency) across tabs: **Overview**, **Analytics**, **Intelligence**,
**Payments**, **Users**, **Security**, **System activity**, **Share links** and
**Storage & AI**.

### OBSIDIAN Intelligence — Administration

Admins get their own assistant (`POST /api/v1/admin/intelligence`) that answers
questions about the platform — *"what's our revenue?"*, *"how many signed in
today?"*, *"how much storage is used?"* — grounded strictly in the aggregate
metrics from `build_insights()`. It is **deterministic and read-only**: it can
never read a document, a key, or another user's private data, and it never
invents a number that is not in the snapshot.

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
  src/pages/role/Admin.tsx          admin console (charts + administration assistant)
  src/components/Charts.tsx         dependency-free SVG pie/bar charts
tests/e2e_smoke.py   end-to-end smoke against the running stack
Dockerfile            single-container deploy (frontend + API, no cloud creds)
docker-compose.yml    one-command deploy
netlify.toml          static frontend deploy
render.yaml           Render blueprint (API service + environment)
infra/template.yaml   AWS SAM stack (S3 · KMS · DynamoDB · API Gateway · Lambda)
docs/DEPLOY.md        deploy guide for every target
```