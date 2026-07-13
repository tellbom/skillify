"""`skillctl list` — list locally installed skills from ~/.skillify/locks (T1.4)."""

from __future__ import annotations

from rich.console import Console

from skillify.common.config import load_config
from skillify.install.lock import list_locks


def run_list(*, console: Console) -> None:
    cfg = load_config()
    locks = list_locks(cfg.locks_dir)
    if not locks:
        console.print("No skills installed.")
        return
    for lock in locks:
        targets = ", ".join(lock.targets) if lock.targets else "(none)"
        # Target brackets are data, not Rich markup. Without this, Rich consumes
        # ``[claude, opencode]`` as a style tag and the target list appears blank.
        console.print(
            f"{lock.identifier}@{lock.version}  targets=[{targets}]  "
            f"{cfg.skills_dir / lock.namespace / lock.name}",
            markup=False,
        )
