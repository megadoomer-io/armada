"""State file recovery for malformed YAML."""

import logging
import pathlib
import shutil
from datetime import datetime

import yaml

logger = logging.getLogger(__name__)


class StateRecoveryError(Exception):
    """Could not recover the state file."""


def recover_state_file(path: pathlib.Path) -> dict[str, object] | None:
    """Attempt to recover a malformed state file.

    Strategy:
    1. Try to parse the file as YAML
    2. If it fails, check for a backup (.bak) and try that
    3. If no backup or backup also fails, return None (caller creates fresh state)
    """
    if not path.exists():
        return None

    raw = path.read_text()

    try:
        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            return data
        logger.warning("State file %s parsed but is not a dict (got %s)", path, type(data).__name__)
    except yaml.YAMLError as e:
        logger.warning("State file %s is malformed: %s", path, e)

    backup_path = path.with_suffix(path.suffix + ".bak")
    if backup_path.exists():
        logger.info("Trying backup at %s", backup_path)
        try:
            backup_data = yaml.safe_load(backup_path.read_text())
            if isinstance(backup_data, dict):
                logger.info("Recovered from backup %s", backup_path)
                shutil.copy2(backup_path, path)
                return backup_data
        except yaml.YAMLError:
            logger.warning("Backup %s is also malformed", backup_path)

    corrupt_name = path.with_suffix(f".corrupt-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.move(str(path), str(corrupt_name))
    logger.warning("Moved corrupt file to %s, starting fresh", corrupt_name)
    return None


def save_with_backup(data: dict[str, object], path: pathlib.Path) -> None:
    """Write state file with a backup of the previous version."""
    if path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup_path)

    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content)
    tmp_path.replace(path)
