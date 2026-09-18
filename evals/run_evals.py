"""
Automated eval harness for /chat. Checks THREE things per the plan's
Phase 4 spec: groundedness/tool-selection (did it route correctly),
citation presence (did it cite a source when it should have), and
safe refusal (did unsupported/unsafe questions escalate).

Usage:
    python evals/run_evals.py --url http://127.0.0.1:8000
Exit code non-zero on any failure -> usable as a CI gate.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

DATASET_PATH = Path(__file__).parent / "golden_dataset.json"


def run_case(client: httpx.Client, case: dict, timeout: float) -> dict:
    resp = client.post("/chat", json={"question": case["question"]}, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()

    passed = True
    reasons = []

    expected_decision = case.get("expected_decision")
    if expected_decision and body.get("decision") != expected_decision:
        passed = False
        reasons.append(f"expected decision '{expected_decision}', got '{body.get('decision')}'")

    expected_escalate = case.get("expected_escalate")
    if expected_escalate is not None and body.get("escalate") != expected_escalate:
        passed = False
        reasons.append(f"expected escalate={expected_escalate}, got {body.get('escalate')}")

    expected_source = case.get("expected_source_contains")
    if expected_source:
        sources = [s.get("document", "") for s in body.get("sources", [])]
        if not any(expected_source in s for s in sources):
            passed = False
            reasons.append(f"expected a source containing '{expected_source}', got {sources}")

    # Section-level check (not just which document) -- proves reranking is
    # actually changing WHICH chunk ends up cited, not just present in the
    # pipeline unused (RAG hardening spec Phase 2 definition of done).
    expected_section = case.get("expected_section_contains")
    if expected_section:
        sections = [s.get("section", "") for s in body.get("sources", [])]
        if not any(expected_section in s for s in sections):
            passed = False
            reasons.append(f"expected a section containing '{expected_section}', got {sections}")

    return {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "reasons": reasons,
        "known_limitation": case.get("known_limitation"),
        "response": body,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.environ.get("INCIDENT_COPILOT_API_KEY", "dev-local-key"))
    parser.add_argument(
        "--timeout", type=float, default=60,
        help="Per-request timeout in seconds. CPU-only LLM inference (e.g. GitHub Actions "
             "runners with no GPU) needs much longer than local/GPU environments.",
    )
    args = parser.parse_args()

    cases = json.loads(DATASET_PATH.read_text())
    results = []
    with httpx.Client(base_url=args.url, headers={"X-API-Key": args.api_key}) as client:
        for case in cases:
            results.append(run_case(client, case, args.timeout))

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\n=== Eval Report: {passed_count}/{len(results)} passed ===\n")
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['id']} ({r['category']})")
        if not r["passed"]:
            for reason in r["reasons"]:
                print(f"    - {reason}")
            if r["known_limitation"]:
                print(f"    NOTE: {r['known_limitation']}")

    if passed_count < len(results):
        print("\nRegression detected — exiting non-zero for CI gate.")
        sys.exit(1)
    print("\nAll eval cases passed.")


if __name__ == "__main__":
    main()
