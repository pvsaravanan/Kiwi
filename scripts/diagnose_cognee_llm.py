"""Ask Cognee's own LLM key what it thinks, and print the raw upstream answer.

Cognee's startup preflight collapses every LLM failure it retries - quota, rate
limit, slow endpoint - into one "connection test timed out after 30s" message,
and its container logs only repeat that same message. This script bypasses
Cognee entirely: it makes one direct call with the exact key the container is
running with, and prints whatever the provider actually said.

    uv run python scripts/diagnose_cognee_llm.py
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

CONTAINER = "kiwi-cognee-1"

ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
}


def container_env() -> dict[str, str]:
    try:
        out = subprocess.run(
            ["docker", "exec", CONTAINER, "env"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        sys.exit("docker not found on PATH - is Docker Desktop installed and running?")
    if out.returncode != 0:
        sys.exit(f"Could not read env from {CONTAINER}; is it running? (docker ps)")
    env = {}
    for line in out.stdout.splitlines():
        key, _, value = line.partition("=")
        env[key] = value
    return env


def main() -> None:
    env = container_env()
    key = env.get("LLM_API_KEY", "")
    provider = env.get("LLM_PROVIDER", "").lower()
    model = env.get("LLM_MODEL", "").split("/", 1)[-1]

    if not key:
        sys.exit("Container has no LLM_API_KEY set - restart .\\kiwi so it rewrites "
                 ".cognee_compose.env from your .env.")

    print(f"container={CONTAINER} provider={provider} model={model}")
    print(f"key={key[:8]}... ({len(key)} chars)")

    url = ENDPOINTS.get(provider)
    if provider == "gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        headers = {"Content-Type": "application/json"}
        body = {"contents": [{"parts": [{"text": "hi"}]}]}
    elif provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
                   "Content-Type": "application/json"}
        body = {"model": model, "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}]}
    elif provider == "openai":
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {"model": model, "max_completion_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}]}
    else:
        sys.exit(f"Don't know how to probe provider {provider!r}.")

    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    started = time.time()
    try:
        resp = urllib.request.urlopen(req, timeout=45)
        print(f"\nHTTP {resp.status} in {time.time()-started:.2f}s - the key works. "
              f"If Cognee still fails, the problem is not this key.")
    except urllib.error.HTTPError as e:
        print(f"\nHTTP {e.code} in {time.time()-started:.2f}s")
        print(e.read().decode()[:800])
        if e.code == 429:
            print("\n-> Quota or rate limit. Cognee retries this until its 30s "
                  "preflight budget expires, then calls it a timeout.")
        elif e.code in (401, 403):
            print("\n-> Credentials rejected. Fix the key in .env, then fully restart "
                  ".\\kiwi (the container bakes the key in at creation time).")
    except Exception as e:
        print(f"\n{type(e).__name__} in {time.time()-started:.2f}s: {e}")
        print("\n-> This one really is a connectivity problem.")


if __name__ == "__main__":
    main()
