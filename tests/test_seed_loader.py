import json
from pathlib import Path
from unittest.mock import MagicMock

from sentinel.seed_loader import format_record, load_seed_data

SEED = Path(__file__).parent.parent / "sentinel" / "seed_data.jsonl"


def test_seed_file_has_20_valid_records():
    lines = [l for l in SEED.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 20
    for line in lines:
        r = json.loads(line)
        for field in ("test_name", "file", "error", "resolution", "timestamp"):
            assert field in r


def test_seed_contains_semantic_matches_for_the_engineered_flake():
    text = SEED.read_text(encoding="utf-8").lower()
    assert "idempotency" in text
    assert "billed twice" in text or "duplicate" in text


def test_load_seed_data_batches_into_one_remember_call(tmp_path):
    seed = tmp_path / "seed.jsonl"
    seed.write_text(
        '{"test_name":"t1","file":"f.py","error":"E1","error_type":"A","stack_trace":"s","resolution":"R1","timestamp":"2026-01-01T00:00:00Z"}\n'
        '{"test_name":"t2","file":"g.py","error":"E2","error_type":"B","stack_trace":"s","resolution":"R2","timestamp":"2026-01-02T00:00:00Z"}\n'
    )
    client = MagicMock()
    count = load_seed_data(client, dataset="sentinel", path=str(seed))
    assert count == 2
    client.remember.assert_called_once()
    text = client.remember.call_args[0][0]
    assert "t1" in text and "t2" in text
    assert client.remember.call_args.kwargs["dataset"] == "sentinel"


def test_format_record_includes_resolution():
    r = {"test_name": "t", "file": "f.py", "error": "E", "error_type": "X",
         "stack_trace": "s", "resolution": "fixed it", "timestamp": "2026-01-01T00:00:00Z"}
    out = format_record(r)
    assert "Resolution: fixed it" in out and "Historical Test Failure" in out
