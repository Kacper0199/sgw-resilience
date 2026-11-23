# Multi-architecture images (linux/amd64 + linux/arm64)

The stack must run on Apple silicon (arm64) laptops and on x86_64 Linux and Windows machines and CI runners. Every third-party image is pinned by a multi-arch index digest, and our two images are built for both platforms.

## Third-party images

Checked on 2026-11-19 with `docker buildx imagetools inspect --raw <image@digest>` (and `docker manifest inspect` for Postgres):

| Image (pinned index digest) | linux/amd64 | linux/arm64 |
| --- | --- | --- |
| `timescale/timescaledb-ha:pg18.6-ts2.31.0@sha256:ad8b5095c9e9f19b3c97794133f1dd80f09da9566a5687f79b6208324b98a388` | `sha256:8dc9836c219fa341447e3e598a856ca4b7692a1fc7077c266dcc12d36dbf41df` | `sha256:6d0ba14da737f7ae4cf02f665cd64a8bc7547e6e891b8ea2c37d4e7a7cd1cbfe` |
| `caddy:2.11-alpine@sha256:003a97808e78...` (base of `sgw/caddy`; the web bundle is built once on the build platform) | yes | yes |
| `openpolicyagent/opa:1.22.4-static@sha256:12cecac5a174...` | yes | yes |
| `ghcr.io/mlflow/mlflow:v3.18.0@sha256:257204c77980...` | yes | yes |
| `alpine/socat:1.8.0.3@sha256:beb4a68d9e4f...` | yes | yes |
| `python:3.12.13-slim-trixie@sha256:229a2c5bfa27...` | yes | yes |
| `ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496...` | yes | yes |

The Postgres digest is the index already on the build machine (built 2026-10-27, labels PostgreSQL 18.6, TimescaleDB 2.31.0, PostGIS 3.6.4, vectorscale 0.9.1). The tag has since moved to `sha256:b548f0d2afa7...`, which also carries both platforms; moving to it is a deliberate pin bump, never implicit. CI must use the same digest as `compose.yaml`.

## Python dependencies

`uv export --frozen --no-dev --no-hashes --no-emit-project -o runtime-req.txt` followed by
`uv pip install --dry-run --python-version 3.12 --python-platform {x86_64,aarch64}-manylinux_2_28 --only-binary :all: --no-binary autograd-gamma -r runtime-req.txt --target <tmp>` resolves all 158 runtime packages from binary wheels on both platforms (exit 0). The only source distribution is `autograd-gamma` 0.5.0 (pure Python, pulled in by lifelines). No package compiles C code during the image build on either platform, so an emulated amd64 build stays fast.

## Our images

| Image | Dockerfile | Context |
| --- | --- | --- |
| `sgw/python` | `docker/python/Dockerfile` | repository root, filtered by `docker/python/Dockerfile.dockerignore` |
| `sgw/mlflow` | `docker/mlflow/Dockerfile` | `docker/mlflow/` |

Local development builds only the native platform (`uv run sgw up --build`). The release build produces one index per image:

```
docker buildx create --name sgw-multi --driver docker-container --use
docker buildx build --platform linux/amd64,linux/arm64 \
  -f docker/python/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) \
  -t ghcr.io/<owner>/sgw-python:<sha> --push .
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/<owner>/sgw-mlflow:<sha> --push docker/mlflow
```

- The `images` job in CI runs these builds on the x86_64 runner with QEMU for arm64, then scans each platform with Trivy and keeps a Syft SBOM.
- Multi-platform output needs either the `docker-container` buildx driver or Docker's containerd image store (on for this build machine); with the classic image store, use `--push` or `--output type=oci`, because a multi-platform result cannot be loaded as one local image.
- Base images are pinned by index digest, so each platform resolves to the manifest listed above; a rebuild on another day gives the same bases.
- The embedding model download in the `models` stage is platform-independent (ONNX); BuildKit runs it once per platform.

## Verification on a new machine

```
docker buildx imagetools inspect ghcr.io/<owner>/sgw-python:<sha>      # lists linux/amd64 and linux/arm64
docker run --rm --platform linux/amd64 ghcr.io/<owner>/sgw-python:<sha> python /opt/sgw/smoke_imports.py
```

`smoke_imports.py` imports every runtime library, fits a small LightGBM model and embeds one string offline; it exits non-zero on any failure.
