"""Upload FireWatch reports to Backblaze B2 (S3-compatible API).

On B2 failure, falls back to copying files into data/reports/local_archive/{run_id}/.

Return contract:
  B2 success:  {"uploaded": [{"file": "...", "url": "..."}],  "error": null,  "storage": "b2"}
  B2 fallback: {"uploaded": [{"file": "...", "path": "..."}], "error": null,  "storage": "local"}
  Hard failure:{"uploaded": [],                               "error": "...", "storage": null}

Callable as:
  - Python module: upload_reports(run_id, file_paths) -> dict
  - CLI script:    python -m app.tools.upload_reports [--run-id ID] [file1 ...]
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import (
    B2_BUCKET, B2_ENDPOINT, B2_ACCESS_KEY, B2_SECRET_KEY,
    B2_PUBLIC_BASE_URL, REPORTS_DIR, LOCAL_ARCHIVE_DIR,
)

log = logging.getLogger("firewatch")

_UPLOAD_EXTENSIONS = {".md", ".json"}
_CONTENT_TYPES = {".md": "text/markdown", ".json": "application/json"}


def upload_reports(
    run_id: str | None = None,
    file_paths: list[str | Path] | None = None,
) -> dict:
    """Upload report files to B2 under firewatch-reports/{run_id}/.

    Falls back to a local archive copy if B2 is unavailable.

    Args:
        run_id:     Run identifier used as the folder prefix. Defaults to 'latest'.
        file_paths: Explicit file list. Defaults to all .md/.json in REPORTS_DIR.

    Returns:
        dict with 'uploaded', 'error', and 'storage' fields.
    """
    paths = _collect_paths(file_paths)
    if not paths:
        return {"uploaded": [], "error": "No report files found", "storage": None}

    # Try B2 first
    if all([B2_BUCKET, B2_ENDPOINT, B2_ACCESS_KEY, B2_SECRET_KEY]):
        result = _upload_to_b2(paths, run_id)
        if result["error"] is None:
            return result
        log.warning("B2 upload failed (%s) — falling back to local archive", result["error"])

    # Fallback: copy to local_archive/
    return _archive_locally(paths, run_id)


def _collect_paths(file_paths: list | None) -> list[Path]:
    """Resolve the list of files to upload."""
    if file_paths:
        return [Path(p) for p in file_paths]
    if not REPORTS_DIR.exists():
        return []
    return sorted(
        p for p in REPORTS_DIR.iterdir()
        if p.is_file() and p.suffix in _UPLOAD_EXTENSIONS
    )


def _upload_to_b2(paths: list[Path], run_id: str | None) -> dict:
    """Attempt B2 upload. Returns result with storage='b2' on success."""
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return {"uploaded": [], "error": "boto3 not installed", "storage": None}

    prefix = f"firewatch-reports/{run_id or 'latest'}"

    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=B2_ENDPOINT,
            aws_access_key_id=B2_ACCESS_KEY,
            aws_secret_access_key=B2_SECRET_KEY,
        )
    except Exception as e:
        return {"uploaded": [], "error": f"B2 client init failed: {e}", "storage": None}

    uploaded = []
    for path in paths:
        if not path.exists():
            continue
        key = f"{prefix}/{path.name}"
        try:
            s3.upload_file(
                str(path), B2_BUCKET, key,
                ExtraArgs={"ContentType": _CONTENT_TYPES.get(path.suffix, "text/plain")},
            )
            url = f"{B2_PUBLIC_BASE_URL.rstrip('/')}/{key}"
            uploaded.append({"file": path.name, "url": url})
            log.info("Uploaded %s -> %s", path.name, url)
        except Exception as e:
            return {"uploaded": uploaded, "error": f"Upload failed for {path.name}: {e}", "storage": None}

    return {"uploaded": uploaded, "error": None, "storage": "b2"}


def _archive_locally(paths: list[Path], run_id: str | None) -> dict:
    """Copy reports to LOCAL_ARCHIVE_DIR/{run_id}/ as B2 fallback."""
    archive_dir = LOCAL_ARCHIVE_DIR / (run_id or "latest")
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived = []
    for path in paths:
        if not path.exists():
            continue
        dest = archive_dir / path.name
        shutil.copy2(path, dest)
        archived.append({"file": path.name, "path": str(dest)})

    log.warning("B2 unavailable — reports archived to local_archive/%s", run_id or "latest")
    return {"uploaded": archived, "error": None, "storage": "local"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(description="Upload FireWatch reports to B2")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("files", nargs="*", help="Specific files (default: all in REPORTS_DIR)")
    args = parser.parse_args()

    result = upload_reports(run_id=args.run_id, file_paths=args.files or None)
    print(json.dumps(result, indent=2))
