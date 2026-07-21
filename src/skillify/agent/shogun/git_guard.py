"""Generate a ``git`` wrapper that structurally blocks remote writes.

This is the enforced (non-prompt-based) half of the push-denial requirement:
a real executable named ``git`` placed ahead of the system git on ``PATH``.
Workers invoking ``git push``, ``git remote add``, ``git remote set-url``, or
``git config credential.*`` get a non-zero exit and no effect on the real
repository — regardless of what any agent has been told to do or not do.
Every other git subcommand (``status``, ``commit``, ``diff``, ``log``, etc.)
is passed straight through to the real ``git`` executable, untouched.

The wrapper is a standalone POSIX shell script; it cannot call back into
Python's event system, so "audit event" here means appending one JSON line
to a caller-supplied ``audit_log`` file whenever it rejects a command. That
write is best-effort: rejection must always win even if the log directory
does not exist or the write otherwise fails, so the log append is wrapped so
its failure can never suppress the non-zero exit.
"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path


class GitGuardError(RuntimeError):
    pass


def write_git_guard(bin_dir: Path, audit_log: Path) -> Path:
    """Write a ``git`` wrapper into ``bin_dir`` that denies remote-write operations.

    ``audit_log`` is the file the wrapper appends one JSON record to whenever
    it rejects a command (timestamp, rejected subcommand, full argv, cwd). A
    failure to write that record never prevents the wrapper from rejecting
    the command and exiting non-zero.
    """
    real_git = shutil.which("git")
    if real_git is None:
        raise GitGuardError("no real git executable found on PATH")

    bin_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    audit_log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    wrapper = bin_dir / "git"
    quoted_git = shlex.quote(real_git)
    quoted_log = shlex.quote(str(audit_log))
    wrapper.write_text(
        "#!/bin/sh\n"
        f"REAL_GIT={quoted_git}\n"
        f"AUDIT_LOG={quoted_log}\n"
        "\n"
        "sub=\"$1\"\n"
        "reject=0\n"
        "case \"$sub\" in\n"
        "  push)\n"
        "    reject=1\n"
        "    ;;\n"
        "  remote)\n"
        "    case \"$2\" in\n"
        "      add|set-url) reject=1 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  config)\n"
        "    for arg in \"$@\"; do\n"
        "      case \"$arg\" in\n"
        "        credential.*) reject=1 ;;\n"
        "      esac\n"
        "    done\n"
        "    ;;\n"
        "esac\n"
        "\n"
        "if [ \"$reject\" -eq 1 ]; then\n"
        "  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)\n"
        "  argv_json=$(printf '%s' \"$*\" | sed 's/\\\\/\\\\\\\\/g; s/\"/\\\\\"/g')\n"
        "  cwd_json=$(pwd | sed 's/\\\\/\\\\\\\\/g; s/\"/\\\\\"/g')\n"
        "  record=\"{\\\"timestamp\\\": \\\"$ts\\\", \\\"rejected_subcommand\\\": \\\"$sub\\\", \"\n"
        "  record=\"$record\\\"argv\\\": \\\"$argv_json\\\", \\\"cwd\\\": \\\"$cwd_json\\\"}\"\n"
        "  { printf '%s\\n' \"$record\" >> \"$AUDIT_LOG\"; } 2>/dev/null || true\n"
        "  echo \"skillify git-guard: rejected '$sub' (remote writes and credential\"\n"
        "  \" config are disabled for Workers)\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "\n"
        "exec \"$REAL_GIT\" \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    return wrapper
