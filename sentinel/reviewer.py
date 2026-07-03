import os
import re
import subprocess

import anthropic
import requests

from sentinel.ingest import IngestResult, format_failure

HISTORY_MARKERS = re.compile(
    r"\b(prior|previous|past|earlier|before|incident|history|recurrence|resolved|matches)\b", re.I)

SYSTEM = """You are Sentinel, a CI reviewer with memory of every past test failure.
Write a short markdown review of the failing test for a pull request comment.
Rules:
- Every claim about past incidents MUST quote the recalled history verbatim or near-verbatim.
- If the recalled history does not support a claim, do not make it.
- If there is no history, say plainly this is a new failure with no prior record.
- End with a concrete suggested next step. Keep it under 200 words."""


def _ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def ground_review(draft: str, history: str | None) -> str:
    """Deterministic lint: drop history-referencing sentences with no 4-gram overlap
    with the recalled text — the assemble→verify→post pattern, verified not vibes."""
    if not history:
        return draft
    corpus = _ngrams(history)
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", draft):
        if HISTORY_MARKERS.search(sentence) and not (_ngrams(sentence) & corpus):
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def fallback_review(result: IngestResult) -> str:
    f = result.failure
    header = f"### Sentinel review — `{f.test_name}`\n\n**Error:** `{f.error_message}`\n\n"
    if result.matched and result.history:
        return header + f"**Recalled history:**\n\n> {result.history}\n\n_Recall via Cognee memory._"
    return header + "No prior incidents match this failure — this is a new failure with no history yet."


def get_diff() -> str:
    try:
        out = subprocess.run(["git", "diff", "HEAD~1", "--stat", "-p"],
                             capture_output=True, text=True, timeout=30).stdout
        return out[:6000]
    except Exception:
        return ""


def build_review(result: IngestResult, diff: str = "") -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback_review(result)
    user = (f"Failing test:\n{format_failure(result.failure)}\n\n"
            f"Recalled history from memory (may be empty):\n{result.history or '(none)'}\n\n"
            f"Diff of the triggering change:\n{diff or '(unavailable)'}")
    try:
        client = anthropic.Anthropic()
        msg = client.messages.create(model="claude-opus-4-8", max_tokens=1024,
                                     system=SYSTEM,
                                     messages=[{"role": "user", "content": user}])
        draft = next((b.text for b in msg.content if b.type == "text"), "")
    except anthropic.APIError as exc:
        print(f"[WARNING] Claude unavailable ({exc}); using fallback review.")
        return fallback_review(result)
    grounded = ground_review(draft, result.history)
    return grounded if grounded else fallback_review(result)


def post_pr_comment(body: str, *, repo: str, pr_number: int, token: str, http=requests) -> None:
    resp = http.post(
        f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments",
        json={"body": body},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"GitHub comment failed: HTTP {resp.status_code}")
    print(f"[REVIEW] Posted PR comment to {repo}#{pr_number}")
