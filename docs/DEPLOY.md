# Deploying OBSIDIAN

OBSIDIAN ships with **one backend code path** (`obsidian.gateway.dispatch`) that
runs unchanged in every environment below. Pick the first option you have
credentials for.

| Option | Needs credentials? | What it gives you |
|---|---|---|
| **1. Docker / any VM** | ❌ none | Full app — UI + API + DynamoDB/S3/KMS (in-process) — on one port |
| **2. AWS (SAM)** | AWS account | Real DynamoDB, S3, KMS, API Gateway, Lambda |
| **3. Netlify** | Netlify account | Static frontend; point `/api` at a running backend |
| **4. Google Cloud** | GCP account | Only needed for the Google OAuth client (works with any host) |

---

## 1. Docker — no cloud credentials at all (recommended first run)

```bash
docker compose up --build
# open http://localhost:8080
```

That is the complete app: the React build is served by the API process, and
DynamoDB / S3 / KMS are served in-process by moto, so **no AWS account, no IAM
keys, no billing**. Every handler is byte-for-byte the one that deploys to
Lambda.

Optional integrations are enabled purely by environment variables (see
`docker-compose.yml` or `--env-file .env`):

```dotenv
# Real OTP email (Gmail app password works)
OBSIDIAN_SMTP_HOST=smtp.gmail.com
OBSIDIAN_SMTP_PORT=587
OBSIDIAN_SMTP_USERNAME=you@gmail.com
OBSIDIAN_SMTP_PASSWORD=your-app-password

# Google sign-in for all four roles
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Razorpay storage payments (test mode)
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
```

Plain `docker build` / `docker run` works too:

```bash
docker build -t obsidian .
docker run -p 8080:8080 --env-file .env obsidian
```

> **Note:** the Docker image runs with `OBSIDIAN_DEV_MODE=true` so sign-up is
> complete without an email provider and payments can be simulated. Set
> `OBSIDIAN_DEV_MODE=false` once SMTP and Razorpay are configured. (Also note
> the in-process AWS mock is ephemeral — data resets when the container does.
> Use option 2 for durable storage.)

### Run without Docker

```bash
# terminal 1 — API
cd backend && pip install -r requirements.txt
OBSIDIAN_STATIC_DIR=../frontend/dist python local/server.py

# terminal 2 — frontend dev server (optional, for hot reload)
cd frontend && npm install && npm run dev
```

---

## 2. AWS (Lambda + API Gateway + S3 + KMS + DynamoDB)

```bash
cd infra
sam build
sam deploy --guided \
  --parameter-overrides \
      PublicBaseUrl=https://app.yourdomain.com \
      GoogleClientId=... GoogleClientSecret=... \
      RazorpayKeyId=... RazorpayKeySecret=... RazorpayWebhookSecret=...
```

Outputs include `HttpApiEndpoint`, `DocumentBucket`, `KmsKeyArn`,
`SecretsManagerSecretArn` and `GoogleRedirectUri` (register that exact value).

The stack provisions 12 DynamoDB tables (SSE-KMS + PITR), a private
KMS-encrypted S3 bucket, a rotating CMK, a Secrets Manager secret, and
CloudWatch alarms for 5xx/429.

---

## 3. Netlify (frontend only)

```bash
npm i -g netlify-cli
netlify deploy --build --prod
```

`netlify.toml` builds `frontend/` and adds an SPA fallback. Replace the origin in
the `/api/v1/*` redirect with your running backend host, and add your Netlify
domain to `OBSIDIAN_ALLOWED_ORIGINS` on the backend.

---

## 4. Google OAuth (all four roles)

The client id/secret are used by the backend; the browser only ever receives
the authorization URL. In the Google Cloud Console OAuth client, register:

- **Authorized JavaScript origin:** the exact public origin (e.g.
  `http://localhost:8080` or `https://app.yourdomain.com`)
- **Authorized redirect URI:** `<public origin>/api/v1/auth/google/callback`

`sandbox`/`test` users must be added while the consent screen is in testing.

---

## Payments (Razorpay)

1. `POST /api/v1/billing/orders` → server creates the order (price fixed
   server-side: ₹3,999 for 15 GB, ₹6,999 for every +10 GB after).
2. Razorpay Checkout collects the payment.
3. `POST /api/v1/billing/verify` → server verifies `HMAC(order_id|payment_id)`
   with the key secret and credits 10 GB.
4. `POST /api/v1/billing/webhook` (optional) → out-of-band confirmation,
   verified against the webhook secret.
