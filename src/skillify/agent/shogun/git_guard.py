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
        "sub=\"\"\n"
        "subarg=\"\"\n"
        "remote_verb=\"\"\n"
        "alias_bypass=0\n"
        "scan_subcommand() {\n"
        "  while [ $# -gt 0 ]; do\n"
        "    case \"$1\" in\n"
        "      -c)\n"
        "        case \"$2\" in\n"
        "          alias.*) alias_bypass=1 ;;\n"
        "        esac\n"
        "        shift 2\n"
        "        continue\n"
        "        ;;\n"
        "      -C|--config-env)\n"
        "        shift 2\n"
        "        continue\n"
        "        ;;\n"
        "      --config-env=*|--git-dir=*|--work-tree=*|--namespace=*|--super-prefix=*|--exec-path=*)\n"
        "        shift\n"
        "        continue\n"
        "        ;;\n"
        "      --exec-path)\n"
        "        shift\n"
        "        continue\n"
        "        ;;\n"
        "      -v|--version|-h|--help|--html-path|--man-path|--info-path|-p|--paginate|-P|--no-pager|--no-replace-objects|--bare|--no-lazy-fetch|--no-optional-locks|--no-advice|--literal-pathspecs|--glob-pathspecs|--noglob-pathspecs|--icase-pathspecs)\n"
        "        shift\n"
        "        continue\n"
        "        ;;\n"
        "      --)\n"
        "        shift\n"
        "        break\n"
        "        ;;\n"
        "      -*)\n"
        "        # unrecognized global-looking option: keep scanning rather than\n"
        "        # risk misreading it as the subcommand\n"
        "        shift\n"
        "        continue\n"
        "        ;;\n"
        "      *)\n"
        "        break\n"
        "        ;;\n"
        "    esac\n"
        "  done\n"
        "  sub=\"$1\"\n"
        "  subarg=\"$2\"\n"
        "  # For \"remote\", find the actual verb (add/set-url/rename/...) past any\n"
        "  # leading options remote accepts before it (git documents -v/--verbose\n"
        "  # as \"must be placed before a subcommand\"). Scan generically, the same\n"
        "  # fail-safe way as above: an unrecognized -* token is treated as needing\n"
        "  # more scanning, never assumed to be the verb.\n"
        "  if [ \"$sub\" = \"remote\" ]; then\n"
        "    shift\n"
        "    while [ $# -gt 0 ]; do\n"
        "      case \"$1\" in\n"
        "        --)\n"
        "          shift\n"
        "          break\n"
        "          ;;\n"
        "        -*)\n"
        "          shift\n"
        "          continue\n"
        "          ;;\n"
        "        *)\n"
        "          break\n"
        "          ;;\n"
        "      esac\n"
        "    done\n"
        "    remote_verb=\"$1\"\n"
        "  fi\n"
        "}\n"
        "scan_subcommand \"$@\"\n"
        "\n"
        "# NOTE (residual limitation): this wrapper can only see arguments passed\n"
        "# to invocations of the `git` executable it shadows on PATH. A Worker\n"
        "# that edits .git/config or ~/.gitconfig directly (text editor, sed,\n"
        "# echo >>), or that sets GIT_CONFIG_GLOBAL/GIT_CONFIG_SYSTEM to point at\n"
        "# a pre-seeded file, can still define an [alias] section without ever\n"
        "# calling git — that is structurally outside what a PATH-shadowing\n"
        "# wrapper can intercept and is an accepted limitation, not a bug here.\n"
        "reject=0\n"
        "if [ \"$alias_bypass\" -eq 1 ]; then\n"
        "  reject=1\n"
        "fi\n"
        "case \"$sub\" in\n"
        "  push)\n"
        "    reject=1\n"
        "    ;;\n"
        "  remote)\n"
        "    case \"$remote_verb\" in\n"
        "      add|set-url) reject=1 ;;\n"
        "    esac\n"
        "    ;;\n"
        "  config)\n"
        "    for arg in \"$@\"; do\n"
        "      case \"$arg\" in\n"
        "        credential.*|alias.*) reject=1 ;;\n"
        "      esac\n"
        "    done\n"
        "    ;;\n"
        "esac\n"
        "\n"
        "if [ \"$reject\" -eq 1 ]; then\n"
        "  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)\n"
        "  argv_json=$(printf '%s' \"$*\" | sed 's/\\\\/\\\\\\\\/g; s/\"/\\\\\"/g')\n"
        "  cwd_json=$(pwd | sed 's/\\\\/\\\\\\\\/g; s/\"/\\\\\"/g')\n"
        "  reject_label=\"$sub\"\n"
        "  if [ \"$alias_bypass\" -eq 1 ] && [ \"$sub\" != \"push\" ] && [ \"$sub\" != \"remote\" ] && [ \"$sub\" != \"config\" ]; then\n"
        "    reject_label=\"alias\"\n"
        "  fi\n"
        "  record=\"{\\\"timestamp\\\": \\\"$ts\\\", \\\"rejected_subcommand\\\": \\\"$reject_label\\\", \"\n"
        "  record=\"$record\\\"argv\\\": \\\"$argv_json\\\", \\\"cwd\\\": \\\"$cwd_json\\\"}\"\n"
        "  { printf '%s\\n' \"$record\" >> \"$AUDIT_LOG\"; } 2>/dev/null || true\n"
        "  echo \"skillify git-guard: rejected '$reject_label' (remote writes, credential config, and alias definitions are disabled for Workers)\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "\n"
        "exec \"$REAL_GIT\" \"$@\"\n",
        encoding="utf-8",
        newline="\n",
    )
    wrapper.chmod(0o700)
    return wrapper
