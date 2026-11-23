"""Spike S2: import every runtime library of the default dependency group and embed one string offline."""

from __future__ import annotations

import importlib
import os
import sys
import time

MODULES = [
    "fastapi",
    "uvicorn",
    "sse_starlette",
    "httpx",
    "psycopg",
    "psycopg_pool",
    "langgraph",
    "langgraph.checkpoint.postgres",
    "langchain_core",
    "langchain_anthropic",
    "anthropic",
    "mlflow",
    "pydantic",
    "yaml",
    "jsonschema",
    "rfc8785",
    "cryptography",
    "argon2",
    "structlog",
    "opentelemetry.sdk",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.exporter.otlp.proto.http.trace_exporter",
    "numpy",
    "pandas",
    "pyarrow",
    "scipy",
    "statsmodels.api",
    "sklearn",
    "lightgbm",
    "shap",
    "mapie",
    "lifelines",
    "highspy",
    "ortools.linear_solver.pywraplp",
    "networkx",
    "geopandas",
    "shapely",
    "pyproj",
    "h3",
    "pandera",
    "fastembed",
    "typer",
]


def main() -> int:
    failed = []
    for name in MODULES:
        started = time.perf_counter()
        try:
            importlib.import_module(name)
        except Exception as error:  # noqa: BLE001
            failed.append(name)
            print(f"FAIL {name}: {type(error).__name__}: {error}")
            continue
        print(f"ok   {name} ({(time.perf_counter() - started) * 1000:.0f} ms)")
    try:
        import lightgbm
        import numpy as np

        model = lightgbm.LGBMRegressor(n_estimators=5, verbose=-1).fit(
            np.arange(40).reshape(-1, 1), np.arange(40)
        )
        print(f"ok   lightgbm fit/predict {model.predict([[3]])[0]:.1f}")
        from fastembed import TextEmbedding

        model_name = os.environ.get("SGW_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
        vector = next(iter(TextEmbedding(model_name).embed(["pump station PS-17 lost feeder"])))
        print(f"ok   fastembed {model_name} offline, dim {len(vector)}")
    except Exception as error:  # noqa: BLE001
        failed.append("runtime probes")
        print(f"FAIL runtime probes: {type(error).__name__}: {error}")
    print(f"{len(MODULES) + 2 - len(failed)}/{len(MODULES) + 2} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
