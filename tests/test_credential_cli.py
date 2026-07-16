from __future__ import annotations

from typer.testing import CliRunner

from skillify.cli.main import app


runner = CliRunner()


def test_credential_add_list_status_and_revoke_do_not_print_secret(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path))
    reference = "local://orders/current-user"
    secret = "top-secret-value"

    added = runner.invoke(app, ["credential", "add", reference, "--secret", secret])
    listed = runner.invoke(app, ["credential", "list"])
    status = runner.invoke(app, ["credential", "status", reference])
    revoked = runner.invoke(app, ["credential", "revoke", reference])

    assert all(result.exit_code == 0 for result in (added, listed, status, revoked))
    output = "".join(result.stdout for result in (added, listed, status, revoked))
    assert secret not in output
    assert reference in output
    assert '"exists": true' in status.stdout
    assert '"revoked": true' in revoked.stdout
