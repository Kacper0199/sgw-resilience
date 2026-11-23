# syntax=docker/dockerfile:1.12
# One Python runtime image for api, worker and llm-gateway (default dependency group only).
# Build context: repository root, filtered by docker/python/Dockerfile.dockerignore.

ARG PYTHON_IMAGE=python:3.12.13-slim-trixie@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project \
 && find /opt/venv -type d -name tests -path "*/site-packages/*" -prune -exec rm -rf {} + \
 && find /opt/venv -name "*.pyi" -delete

FROM deps AS models
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
RUN /opt/venv/bin/python -c "import sys; from fastembed import TextEmbedding; TextEmbedding(sys.argv[1], cache_dir='/opt/models')" "${EMBED_MODEL}" \
 && chmod -R a+rX,go-w /opt/models

FROM ${PYTHON_IMAGE} AS runtime
ARG GIT_SHA=unknown
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
LABEL org.opencontainers.image.title="sgw-python" \
      org.opencontainers.image.description="SGW Resilience Decision Platform Python runtime (api, worker, llm-gateway)" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${GIT_SHA}"
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 sgw \
 && useradd --system --uid 10001 --gid sgw --home-dir /app --no-create-home --shell /usr/sbin/nologin sgw
COPY --from=deps /opt/venv /opt/venv
COPY --from=models /opt/models /opt/models
COPY docker/python/placeholder.py docker/python/smoke_imports.py /opt/sgw/
COPY src/ /app/src/
RUN --mount=type=bind,target=/ctx \
    for d in services policy contracts data/numbers data/seed data/fixtures data/synthetic data/scenarios data/artefacts data/open \
      data/corpus data/reference evals/reports; do \
      if [ -d "/ctx/$d" ]; then mkdir -p "/app/$(dirname "$d")" && cp -R "/ctx/$d" "/app/$d"; fi; \
    done
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src:/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/models \
    SGW_EMBED_MODEL=${EMBED_MODEL} \
    HF_HUB_OFFLINE=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    SGW_GIT_SHA=${GIT_SHA}
WORKDIR /app
USER 10001:10001
CMD ["python", "/opt/sgw/placeholder.py"]
