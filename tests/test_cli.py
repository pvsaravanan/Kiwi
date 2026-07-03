from pathlib import Path
from unittest.mock import patch

from sentinel import cli

FIXTURE = str(Path(__file__).parent / "fixtures" / "simple_failure.xml")


def test_ingest_prints_review(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.object(cli, "CogneeClient") as mock_cls:
        mock_cls.return_value.settings.dataset = "sentinel"
        mock_cls.return_value.recall.return_value = [{"text": "prior: idempotency key fix"}]
        code = cli.main(["ingest", FIXTURE, "--run-id", "r1", "--review"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Sentinel review" in out or "idempotency" in out


def test_ingest_ci_mode_never_fails(capsys):
    with patch.object(cli, "CogneeClient", side_effect=RuntimeError("no env")):
        code = cli.main(["ingest", FIXTURE, "--ci"])
    assert code == 0


def test_confirm_invokes_lifecycle():
    with patch.object(cli, "CogneeClient") as mock_cls, \
         patch.object(cli, "confirm") as mock_confirm:
        mock_cls.return_value.settings.dataset = "sentinel"
        code = cli.main(["confirm", "test_x", "fixed by idempotency key", "--run-id", "r9"])
    assert code == 0
    assert mock_confirm.call_args.kwargs["test_name"] == "test_x"
    assert mock_confirm.call_args.kwargs["dataset"] == "sentinel"


def test_forget_invokes_lifecycle():
    with patch.object(cli, "CogneeClient"), patch.object(cli, "forget_dataset") as mock_forget:
        code = cli.main(["forget", "--dataset", "sentinel_smoke", "--memory-only"])
    assert code == 0
    assert mock_forget.call_args.kwargs == {"dataset": "sentinel_smoke", "memory_only": True}
