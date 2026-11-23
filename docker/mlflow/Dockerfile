# syntax=docker/dockerfile:1.12
# MLflow tracking server and model registry, non-root, SQLite metadata and served artifacts in one volume.
ARG MLFLOW_IMAGE=ghcr.io/mlflow/mlflow:v3.18.0@sha256:257204c77980b0f3450a26eb6089e487603fcdd4509529eadaf88f90669f5c13
FROM ${MLFLOW_IMAGE}
RUN useradd --system --uid 10002 --home-dir /mlflow --create-home --shell /usr/sbin/nologin mlflow \
 && mkdir -p /mlflow/db /mlflow/artifacts \
 && chown -R mlflow:mlflow /mlflow
ENV MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false \
    PYTHONDONTWRITEBYTECODE=1
USER 10002:10002
WORKDIR /mlflow
EXPOSE 5001
CMD ["mlflow", "server", \
     "--host", "0.0.0.0", "--port", "5001", "--workers", "1", \
     "--backend-store-uri", "sqlite:////mlflow/db/mlflow.db", \
     "--artifacts-destination", "/mlflow/artifacts", "--serve-artifacts", \
     "--allowed-hosts", "mlflow,mlflow:5001,localhost,localhost:5001,127.0.0.1,127.0.0.1:5001"]
