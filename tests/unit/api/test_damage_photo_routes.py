"""Damage-photo preview routes: one photo's scores per label, and the full-size image
downloaded to this machine, served only by a queued image id from inside the images folder with matching
sha256; without the local file the committed thumbnail is served instead. No external links."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sgw.api.deps import current_user
from sgw.api.errors import install_error_handlers
from sgw.api.routers.damage import router
from sgw.contracts.api_models import DamagePhotoDetail
from sgw.models.cv import images, read

ROOT = Path(__file__).resolve().parents[3]
THUMB = ROOT / "data/artefacts/cv/thumbs/test_0016.jpg"
PHOTO = "ladi-v2-test-0016"


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(images.IMAGES_ENV, str(tmp_path))
    return tmp_path


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[current_user] = lambda: object()
    with TestClient(app) as c:
        yield c


def _sha(image_id: str) -> str:
    return str(images._sample()[image_id]["sha256"])


def test_detail_lists_damage_scores_highest_first(client: TestClient, folder: Path) -> None:
    r = client.get(f"/api/damage/photos/{PHOTO}")
    assert r.status_code == 200
    d = DamagePhotoDetail.model_validate(r.json())
    scores = [label.score for label in d.labels]
    assert scores == sorted(scores, reverse=True) and len(d.labels) == len(images.DAMAGE_LABELS)
    assert "roads_any" not in {label.label for label in d.labels}
    assert d.image_url == f"/api/damage/images/{PHOTO}" and d.full_size is False
    assert d.licence == "CC-BY-4.0" and d.dataset == "MITLL/LADI-v2-dataset"
    assert "huggingface" not in d.image_url


def test_image_falls_back_to_the_thumbnail(client: TestClient, folder: Path) -> None:
    r = client.get(f"/api/damage/images/{PHOTO}")
    assert r.status_code == 200 and r.headers["x-sgw-image"] == "thumbnail"
    assert r.content == THUMB.read_bytes()
    assert r.headers["content-type"] == "image/jpeg" and r.headers["x-content-type-options"] == "nosniff"


def test_a_verified_local_file_is_served_full_size(
    client: TestClient, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"\xff\xd8\xff\xe0 full-size stand-in"
    (folder / "test_0016.jpg").write_bytes(body)
    item = {**images._sample()[PHOTO], "sha256": hashlib.sha256(body).hexdigest()}
    monkeypatch.setattr(images, "_sample", lambda: {PHOTO: item})
    r = client.get(f"/api/damage/images/{PHOTO}")
    assert r.headers["x-sgw-image"] == "full" and r.content == body
    assert client.get(f"/api/damage/photos/{PHOTO}").json()["full_size"] is True
    again = client.get(f"/api/damage/images/{PHOTO}", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_a_tampered_file_is_not_served(client: TestClient, folder: Path) -> None:
    (folder / "test_0016.jpg").write_bytes(b"\xff\xd8 not the recorded photo")
    r = client.get(f"/api/damage/images/{PHOTO}")
    assert r.headers["x-sgw-image"] == "thumbnail"


def test_a_symlink_out_of_the_folder_is_not_followed(tmp_path: Path, folder: Path) -> None:
    outside = tmp_path.parent / "outside_test_0016.jpg"
    outside.write_bytes(b"secret")
    (folder / "test_0016.jpg").symlink_to(outside)
    assert images.image_path(PHOTO) is None
    assert _sha(PHOTO)


@pytest.mark.parametrize(
    "bad", ["..%2F..%2Fetc%2Fpasswd", "ladi-v2-test-9999", "LADI-V2-TEST-0016", "a" * 80, "test_0016.jpg"]
)
def test_only_queued_ids_are_served(client: TestClient, folder: Path, bad: str) -> None:
    assert client.get(f"/api/damage/images/{bad}").status_code == 404
    assert client.get(f"/api/damage/photos/{bad}").status_code == 404


def test_every_queued_photo_is_in_the_sample() -> None:
    queued = {r["image_id"] for r in read._load(read.QUEUE_PATH)["rows"]}
    assert queued <= set(images._sample())
