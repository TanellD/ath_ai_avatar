"""Ahead-of-demo download and checksum verification for GigaAM artefacts.

``gigaam.load_model`` silently downloads a missing checkpoint on first use, so an
unprepared cache turns a demo start into a ~450 MB transfer from an upstream CDN
whose only visible symptom is a ``/ready`` that never flips.  Every artefact is
pinned in ``models.lock.json``; ``make gigaam-setup`` fetches and verifies them
up front and the normal worker start stays offline.
"""

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

LOCK_PATH = Path(__file__).resolve().parent.parent / "models.lock.json"

_CHUNK_BYTES = 1 << 20
_DOWNLOAD_RETRIES = 3


class ModelSetupError(RuntimeError):
    """An artefact is missing, truncated, or does not match the pinned digest."""


@dataclass(frozen=True)
class PinnedFile:
    name: str
    size: int
    sha256: str
    md5: str | None = None


def load_pinned_files(model: str, lock_path: Path | None = None) -> tuple[str, list[PinnedFile]]:
    """Read the lock file and return the source URL plus the pinned artefacts."""
    lock_path = LOCK_PATH if lock_path is None else lock_path
    try:
        manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ModelSetupError(f"lock file is missing: {lock_path}") from exc
    except json.JSONDecodeError as exc:
        raise ModelSetupError(f"lock file is malformed: {lock_path}: {exc}") from exc

    entry = manifest.get("models", {}).get(model)
    if entry is None:
        known = ", ".join(sorted(manifest.get("models", {}))) or "none"
        raise ModelSetupError(f"model {model!r} is not pinned (available: {known})")

    files = [
        PinnedFile(
            name=item["name"],
            size=int(item["size"]),
            sha256=item["sha256"],
            md5=item.get("md5"),
        )
        for item in entry["files"]
    ]
    return manifest["source"].rstrip("/"), files


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def describe_mismatch(path: Path, pinned: PinnedFile, *, deep: bool = True) -> str | None:
    """Describe how the file differs from the lock file, or None when it matches.

    ``deep=False`` only checks presence and size.  That is enough to decide
    whether the cache is complete and avoids hashing 450 MB on every start.
    """
    if not path.exists():
        return "file is missing"
    actual_size = path.stat().st_size
    if actual_size != pinned.size:
        return f"size {actual_size} instead of {pinned.size}"
    if not deep:
        return None
    actual_sha = file_digest(path, "sha256")
    if actual_sha != pinned.sha256:
        return f"sha256 {actual_sha} instead of {pinned.sha256}"
    if pinned.md5 is not None:
        actual_md5 = file_digest(path, "md5")
        if actual_md5 != pinned.md5:
            return f"md5 {actual_md5} instead of {pinned.md5}"
    return None


def download(url: str, path: Path) -> None:
    """Download through a temporary file so an interrupt cannot leave a stub."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, _DOWNLOAD_RETRIES + 1):
        try:
            with urllib.request.urlopen(url) as source, temporary.open("wb") as output:
                while chunk := source.read(_CHUNK_BYTES):
                    output.write(chunk)
            temporary.replace(path)
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            print(f"  attempt {attempt}/{_DOWNLOAD_RETRIES} failed: {exc}", file=sys.stderr)
            continue
        else:
            return
    raise ModelSetupError(f"could not download {url}: {last_error}")


def ensure_file(cache_dir: Path, source: str, pinned: PinnedFile, *, check_only: bool) -> bool:
    """Prepare a single artefact. Returns True when it had to be downloaded."""
    path = cache_dir / pinned.name
    mismatch = describe_mismatch(path, pinned)
    if mismatch is None:
        print(f"  {pinned.name}: matches the lock file")
        return False
    if check_only:
        raise ModelSetupError(f"{pinned.name}: {mismatch}")

    print(f"  {pinned.name}: {mismatch}, downloading {pinned.size / 1e6:.1f} MB")
    path.unlink(missing_ok=True)
    download(f"{source}/{pinned.name}", path)

    mismatch = describe_mismatch(path, pinned)
    if mismatch is not None:
        # A corrupt artefact must not survive: gigaam reuses whatever is cached
        # and would only fail its own assert during the demo.
        path.unlink(missing_ok=True)
        raise ModelSetupError(f"{pinned.name}: after download {mismatch}")
    print(f"  {pinned.name}: downloaded and verified")
    return True


def verify_cache(model: str, cache_dir: Path) -> None:
    """Quietly assert the cache is complete; raises ModelSetupError when it is not.

    Called on worker start. Digests are not recomputed here: ``make gigaam-setup``
    does the full comparison and gigaam asserts the checkpoint md5 in load_model.
    """
    _, files = load_pinned_files(model)
    for pinned in files:
        mismatch = describe_mismatch(cache_dir / pinned.name, pinned, deep=False)
        if mismatch is not None:
            raise ModelSetupError(f"{pinned.name}: {mismatch}")


def prepare(model: str, cache_dir: Path, *, check_only: bool = False) -> None:
    source, files = load_pinned_files(model)
    print(f"GigaAM {model} -> {cache_dir}")
    for pinned in files:
        ensure_file(cache_dir, source, pinned, check_only=check_only)


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Prepare the local GigaAM model cache")
    parser.add_argument("--model", default=settings.gigaam_model)
    parser.add_argument("--cache-dir", type=Path, default=Path(settings.gigaam_cache_dir))
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="verify the cache without downloading anything",
    )
    args = parser.parse_args(argv)

    try:
        prepare(args.model, args.cache_dir, check_only=args.check_only)
    except ModelSetupError as exc:
        print(f"GigaAM setup failed: {exc}", file=sys.stderr)
        return 1
    print("GigaAM cache is ready for an offline start")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
