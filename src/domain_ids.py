"""Canonical domain-id handling and compatibility lookup for local stores."""

from pathlib import Path
import shutil
import uuid


def normalize_domain_id(value: str) -> str:
    """Return the canonical domain id used by API and storage layers."""
    return value.strip().lower()


def get_domain_store_path(base_path: str | Path, domain_id: str) -> Path:
    """Return the canonical path, falling back to an existing case variant."""
    base = Path(base_path)
    normalized_id = normalize_domain_id(domain_id)
    canonical_path = base / normalized_id
    if canonical_path.exists() or not base.exists():
        return canonical_path

    for child in base.iterdir():
        if child.is_dir() and child.name.lower() == normalized_id:
            return child
    return canonical_path


def swap_store_directories(staging_path: Path, target_path: Path) -> None:
    """Replace a store only after staging is complete, restoring on failure."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = target_path.parent / f".{target_path.name}.backup-{uuid.uuid4().hex}"
    target_moved = False
    try:
        if target_path.exists():
            target_path.rename(backup_path)
            target_moved = True
        staging_path.rename(target_path)
    except Exception:
        if target_moved and not target_path.exists() and backup_path.exists():
            backup_path.rename(target_path)
        raise
    else:
        if backup_path.exists():
            shutil.rmtree(backup_path)
