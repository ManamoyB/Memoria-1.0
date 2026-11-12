# Render Deployment & GitHub Preparation Guide

This guide documents how to prepare the repository for GitHub and deploy the **MemoriaOS Document Reader Agent** to **Render**.

---

## 1. Cloud Readiness Highlights

- **Dynamic Render `PORT`**: `app/core/config.py` reads `AliasChoices("PORT", "MEMORIA_PORT")` so Render's injected `PORT` environment variable works automatically.
- **Ephemeral Temporary Storage**: By default (`MEMORIA_UPLOAD_DIR` unset), `UploadStorageService` writes to the OS ephemeral temp directory (`tempfile.gettempdir()/memoria_uploads`), avoiding dependency on persistent local disk.
- **Guaranteed File Cleanup**:
  - `ProcessingController` wraps every stream/bytes upload in `try ... finally` and deletes the temp artifact immediately when `MEMORIA_CLEANUP_TEMP_UPLOADS=true`.
  - On startup, FastAPI lifespan calls `storage.purge_stale_files(max_age_seconds=3600)` to clean up any orphaned artifacts from prior container restarts.
- **Structured Production Logging**: Setting `MEMORIA_ENVIRONMENT=production` (or `staging`) switches root logging to single-line JSON (`timestamp`, `level`, `logger`, `message`, `request_id`, `document_id`, `exception`) for Render Log Streams.
- **CORS Restrictions**: `CORSMiddleware` reads `MEMORIA_CORS_ORIGINS` (comma-separated) and restricts methods to `GET, POST, OPTIONS`, headers to `Authorization, Content-Type, X-Request-ID`, and exposes `X-Request-ID`. Wildcard `*` automatically disables `allow_credentials`.

---

## 2. GitHub Pre-Push Checklist

Verify these repository hygiene items before pushing to GitHub:

1. **`.gitignore` excludes**:
   - Virtual environments (`.venv/`, `venv/`, `env/`)
   - Python caches (`__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`)
   - Uploaded documents (`storage/uploads/*`, keeping `storage/uploads/.gitkeep`)
   - Local secrets (`.env`, `.env.local`, while keeping `.env.example`)
   - Local database files (`*.db`, `*.sqlite`, `*.sqlite3`) and `tmp/`
2. **`requirements.txt` & `pyproject.toml`**:
   - Production dependencies pinned cleanly (`fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `python-multipart`, `PyMuPDF`, `python-docx`, `pandas`).
   - Test dependencies (`pytest`, `httpx`) included so Render or GitHub Actions CI can run verification.
3. **No hardcoded secrets**:
   - Confirm no API keys or credentials exist in `app/`, `tests/`, or `.env.example`.

---

## 3. Deploy via Render Blueprint (`render.yaml`)

1. Push the repository to GitHub.
2. In the Render Dashboard, choose **New + -> Blueprint** and connect your GitHub repository.
3. Render automatically detects `render.yaml` at the repo root:
   - **Runtime**: `python` (`PYTHON_VERSION=3.12.8`)
   - **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
   - **Health Check Path**: `/health`
4. Set **`MEMORIA_CORS_ORIGINS`** in Render's Environment panel to your exact frontend or orchestrator origins (for example: `https://memoria-ui.onrender.com,https://orchestrator.memoriaos.internal`).

---

## 4. Manual Render Web Service Setup

If creating a Web Service manually instead of a Blueprint:

- **Environment**: Python 3 (`PYTHON_VERSION=3.12.8`)
- **Build Command**: `pip install --upgrade pip && pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
- **Health Check Path**: `/health`
- **Recommended Environment Variables**:
  - `MEMORIA_ENVIRONMENT=production`
  - `MEMORIA_LOG_LEVEL=INFO`
  - `MEMORIA_UPLOAD_DIR=/tmp/memoria_uploads`
  - `MEMORIA_CLEANUP_TEMP_UPLOADS=true`
  - `MEMORIA_MAX_FILE_SIZE_MB=25`
  - `MEMORIA_MAX_BATCH_FILES=10`
  - `MEMORIA_CHUNK_SIZE=3000`
  - `MEMORIA_CHUNK_OVERLAP=300`
  - `MEMORIA_CSV_MAX_ROWS=10000`
  - `MEMORIA_REQUEST_TIMEOUT_SECONDS=30.0`
  - `MEMORIA_OCR_ENABLED=false`
  - `MEMORIA_CORS_ORIGINS=https://your-allowed-origin.example.com`

---

## 5. Post-Deploy Verification

```bash
# 1. Health & service info
curl -sS https://<your-service>.onrender.com/health
curl -sS https://<your-service>.onrender.com/api/v1/documents/supported-formats

# 2. Sample document extraction
curl -sS -X POST "https://<your-service>.onrender.com/api/v1/documents/process" \
  -F "file=@README.md"
```
