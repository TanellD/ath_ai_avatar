import hashlib
import json
from pathlib import Path

import pytest

from app.setup_models import (
    ModelSetupError,
    describe_mismatch,
    load_pinned_files,
    prepare,
    verify_cache,
)

MODEL = "v3_e2e_ctc"
PAYLOAD = b"gigaam weights"


def _lock(tmp_path: Path, payload: bytes = PAYLOAD) -> Path:
    lock = tmp_path / "models.lock.json"
    lock.write_text(
        json.dumps(
            {
                "source": "https://example.invalid/GigaAM",
                "models": {
                    MODEL: {
                        "files": [
                            {
                                "name": f"{MODEL}.ckpt",
                                "size": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest(),
                                "md5": hashlib.md5(payload).hexdigest(),
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return lock


@pytest.fixture
def pinned_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    lock = _lock(tmp_path)
    monkeypatch.setattr("app.setup_models.LOCK_PATH", lock)
    return lock


def test_repository_manifest_pins_the_configured_model() -> None:
    source, files = load_pinned_files(MODEL)

    assert source.startswith("https://")
    names = {file.name for file in files}
    # An e2e model is useless without its tokenizer: gigaam wires it into decoding.
    assert names == {f"{MODEL}.ckpt", f"{MODEL}_tokenizer.model"}
    assert all(len(file.sha256) == 64 for file in files)


def test_prepare_downloads_missing_file_and_verifies_it(
    tmp_path: Path, pinned_lock: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"

    def fake_download(url: str, path: Path) -> None:
        assert url == f"https://example.invalid/GigaAM/{MODEL}.ckpt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PAYLOAD)

    monkeypatch.setattr("app.setup_models.download", fake_download)
    prepare(MODEL, cache)

    assert (cache / f"{MODEL}.ckpt").read_bytes() == PAYLOAD


def test_prepare_removes_artifact_that_fails_checksum(
    tmp_path: Path, pinned_lock: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"

    def corrupt_download(url: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Same size, different bytes: only a digest catches this.
        path.write_bytes(b"x" * len(PAYLOAD))

    monkeypatch.setattr("app.setup_models.download", corrupt_download)

    with pytest.raises(ModelSetupError, match="sha256"):
        prepare(MODEL, cache)
    # A corrupt cache must not survive: gigaam would reuse it as is.
    assert not (cache / f"{MODEL}.ckpt").exists()


def test_check_only_never_downloads(
    tmp_path: Path, pinned_lock: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_download(url: str, path: Path) -> None:
        raise AssertionError("check-only must not reach the network")

    monkeypatch.setattr("app.setup_models.download", forbidden_download)

    with pytest.raises(ModelSetupError, match="file is missing"):
        prepare(MODEL, tmp_path / "cache", check_only=True)


def test_verify_cache_accepts_full_cache_and_rejects_truncated_one(
    tmp_path: Path, pinned_lock: Path
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    artifact = cache / f"{MODEL}.ckpt"
    artifact.write_bytes(PAYLOAD)

    verify_cache(MODEL, cache)

    artifact.write_bytes(PAYLOAD[:-1])
    with pytest.raises(ModelSetupError, match="size"):
        verify_cache(MODEL, cache)


def test_shallow_check_skips_hashing(tmp_path: Path) -> None:
    _lock(tmp_path)
    _, files = load_pinned_files(MODEL, tmp_path / "models.lock.json")
    pinned = files[0]
    artifact = tmp_path / pinned.name
    artifact.write_bytes(b"y" * len(PAYLOAD))

    # Same size, different bytes: the worker start skips this on purpose, and
    # gigaam still asserts the checkpoint md5 itself in load_model.
    assert describe_mismatch(artifact, pinned, deep=False) is None
    assert describe_mismatch(artifact, pinned) is not None


def test_unknown_model_is_reported_with_available_names(pinned_lock: Path) -> None:
    with pytest.raises(ModelSetupError, match="is not pinned"):
        load_pinned_files("v3_rnnt")
