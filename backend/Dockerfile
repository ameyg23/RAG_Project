# syntax=docker/dockerfile:1
#
# Cloud Run deployment image (ADR-19) — a documented FALLBACK, not the
# current deploy target as of ADR-20 (backend hosting reverted to Render,
# `render.yaml`, once the real memory driver was fixed directly instead of
# switching platforms). Kept, unused, in case a future feature ever pushes
# memory back over Render's free-tier ceiling. If this path is picked back
# up: built automatically by Cloud Build via Cloud Run's "continuously
# deploy from a repository" flow — see docs/DEPLOYMENT.md's "Backend —
# Google Cloud Run" section for the exact console steps, in particular the
# build-context/source-location setting (must point at `backend/`, since
# this Dockerfile lives here, not at the repo root).
#
# Python version: 3.13, matching backend/pyproject.toml's
# `target-version = "py313"` and .github/workflows/ci.yml's pinned
# `python-version: "3.13"` — kept in sync deliberately, not guessed.
FROM python:3.13-slim

# Unbuffered stdout/stderr so `print()`/logging output reaches Cloud Run's
# log viewer immediately instead of sitting in a buffer; skip .pyc writes
# since this container is rebuilt from source on every deploy anyway (no
# benefit to bytecode caching across runs).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Cap numpy/scipy/onnxruntime's BLAS/thread pools — identical rationale and
# values to render.yaml's env vars: each unbounded OpenMP/MKL/OpenBLAS thread
# pool adds its own stack + arena memory on top of model weights, and Cloud
# Run's CPU allocation (whole or fractional vCPUs depending on the chosen
# tier) gains negligible speed from multithreading here anyway. No behavior
# change, same memory-safety motivation that (independently of this)
# prompted the ADR-17 reranker revert and the ADR-20 embedding-runtime swap.
ENV OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

WORKDIR /app

# Install dependencies in their own layer, before copying source, so Cloud
# Build's layer cache is reused across source-only changes (only
# requirements.txt changing invalidates this layer).
#
# requirements.txt installs `fastembed` (ONNX Runtime) for local embeddings
# as of ADR-20 — no torch/CUDA wheel pin needed here at all (that pin was
# removed along with sentence-transformers/torch; see requirements.txt's
# own comment and ADR-20 for why).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source (.dockerignore excludes .venv/, __pycache__/, tests/,
# .env, and other files not needed at runtime).
COPY . .

# Cloud Run injects the actual listen port via the $PORT env var at
# container start (it is NOT necessarily 8080 in production, even though
# 8080 is the documented default/local fallback) — the port must always be
# read dynamically from the environment, never hardcoded. ENV PORT=8080
# here only sets a fallback for running this image outside Cloud Run (e.g.
# `docker run -p 8080:8080 <image>`); Cloud Run overrides it at deploy time.
ENV PORT=8080
EXPOSE 8080

# Shell form (not exec-form JSON array) so $PORT undergoes shell expansion —
# the same pattern already used in render.yaml's startCommand. Do not
# rewrite this as ["uvicorn", "main:app", ..., "--port", "$PORT"]; the exec
# form does not expand environment variables and would pass the literal
# string "$PORT" to uvicorn.
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
