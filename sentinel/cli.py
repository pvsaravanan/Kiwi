import argparse
import os
import sys

from sentinel.cognee_client import CogneeClient
from sentinel.ingest import process_report
from sentinel.lifecycle import confirm, forget_dataset
from sentinel.reviewer import build_review, get_diff, post_pr_comment
from sentinel.seed_loader import load_seed_data


def main(argv: list[str] | None = None) -> int:
    # Cognee's LLM output contains characters (e.g. U+202F) that Windows
    # cp1252 consoles can't encode — never let printing kill the pipeline.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="sentinel", description="CI memory + QA reviewer on Cognee")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="bulk-load historical failures")

    p = sub.add_parser("ingest", help="process a JUnit XML report")
    p.add_argument("xml_path")
    p.add_argument("--run-id", default=None)
    p.add_argument("--review", action="store_true", help="write a review per failure")
    p.add_argument("--post", action="store_true", help="post review as PR comment")
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    p.add_argument("--pr", type=int, default=None)
    p.add_argument("--ci", action="store_true", help="never exit non-zero")

    p = sub.add_parser("confirm", help="engineer confirms same-issue (improve)")
    p.add_argument("test_name")
    p.add_argument("resolution")
    p.add_argument("--run-id", required=True)

    p = sub.add_parser("forget", help="prune memory")
    p.add_argument("--dataset", required=True)
    p.add_argument("--memory-only", action="store_true")

    args = ap.parse_args(argv)
    try:
        return _dispatch(args)
    except Exception as exc:
        print(f"[SENTINEL ERROR] {exc}")
        return 0 if getattr(args, "ci", False) else 1


def _dispatch(args) -> int:
    if args.command == "seed":
        client = CogneeClient()
        load_seed_data(client, dataset=client.settings.dataset)
        return 0

    if args.command == "ingest":
        client = CogneeClient()
        results = process_report(args.xml_path, run_id=args.run_id,
                                 client=client, dataset=client.settings.dataset)
        if args.review:
            diff = get_diff()
            for result in results:
                review = build_review(result, diff=diff)
                print("\n" + review)
                if args.post and args.repo and args.pr:
                    post_pr_comment(review, repo=args.repo, pr_number=args.pr,
                                    token=os.environ["GITHUB_TOKEN"])
        return 0

    if args.command == "confirm":
        client = CogneeClient()
        confirm(client, test_name=args.test_name, resolution=args.resolution,
                run_id=args.run_id, dataset=client.settings.dataset)
        return 0

    if args.command == "forget":
        forget_dataset(CogneeClient(), dataset=args.dataset, memory_only=args.memory_only)
        return 0
    return 1
