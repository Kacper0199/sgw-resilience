# syntax=docker/dockerfile:1.12
# Edge image: the web app built from web/ with the frozen pnpm lockfile, served by the pinned Caddy with the
# repository Caddyfile. No Node on the host. Build context: repository root, filtered by
# docker/caddy/Dockerfile.dockerignore (web sources and lockfiles only, never node_modules, dist or .env).

ARG NODE_IMAGE=node:24.22.3-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5
ARG CADDY_IMAGE=caddy:2.11-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0

# The bundle is architecture-independent: build it once on the build platform, no QEMU for Node in multi-arch builds.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS web
ENV CI=1 \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    COREPACK_HOME=/opt/corepack \
    npm_config_store_dir=/pnpm/store \
    npm_config_package_import_method=copy
WORKDIR /build
COPY package.json ./
RUN corepack enable pnpm && corepack install
COPY pnpm-lock.yaml pnpm-workspace.yaml ./
COPY web/package.json web/
RUN --mount=type=cache,id=sgw-pnpm-store,target=/pnpm/store,sharing=locked \
    pnpm install --frozen-lockfile --ignore-scripts --filter @sgw/web
COPY web/ web/
COPY docker/caddy/check-no-inline-scripts.mjs docker-check-no-inline-scripts.mjs
RUN pnpm -C web build \
 && rm -f web/dist/mockServiceWorker.js \
 && if grep -rlE 'mockServiceWorker|setupWorker' web/dist; then echo "mock code in web/dist" >&2; exit 1; fi \
 && node docker-check-no-inline-scripts.mjs web/dist/index.html

FROM ${CADDY_IMAGE} AS runtime
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="sgw-caddy" \
      org.opencontainers.image.description="SGW Resilience Decision Platform edge: web app and /api reverse proxy" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${GIT_SHA}"
COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /build/web/dist /srv
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
 && chmod -R a+rX,go-w /srv /etc/caddy
USER 65534:65534
EXPOSE 8080 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 --start-period=10s \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
