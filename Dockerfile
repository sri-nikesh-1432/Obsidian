# OBSIDIAN — single-container deployment.
#
# Builds the React frontend, then runs the API with the same handlers that
# deploy to AWS Lambda. AWS services (DynamoDB, S3, KMS) are served in-process
# by moto, so this image needs NO AWS account and NO cloud credentials — you
# only supply the optional Google / Razorpay / SMTP values to switch those on.
#
#   docker build -t obsidian .
#   docker run -p 8080:8080 --env-file .env obsidian
#
# Then open http://localhost:8080

# ---------------------------------------------------------------- web build
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------ runtime
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=web /web/dist ./web

# Self-contained defaults: in-process AWS, no external services required.
# Override any of these with -e / --env-file for Google, Razorpay or SMTP.
# The public origin defaults to the Netlify site that proxies /api/v1/* to this
# service; override OBSIDIAN_*_BASE_URL and OBSIDIAN_ALLOWED_ORIGINS when the
# service answers on a different origin.
ENV OBSIDIAN_LOCAL_AWS=true \
    OBSIDIAN_DEV_MODE=true \
    OBSIDIAN_API_HOST=0.0.0.0 \
    OBSIDIAN_API_PORT=8080 \
    OBSIDIAN_STATIC_DIR=/app/web \
    OBSIDIAN_PUBLIC_BASE_URL=https://obsidiancloud.netlify.app \
    OBSIDIAN_API_BASE_URL=https://obsidiancloud.netlify.app/api/v1 \
    OBSIDIAN_ALLOWED_ORIGINS=https://obsidiancloud.netlify.app,https://obsidian-abax.onrender.com

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

CMD ["python", "backend/local/server.py"]
