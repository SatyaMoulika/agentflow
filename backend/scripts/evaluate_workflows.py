"""Evaluate synthetic workflow requests against the configured provider, by explicit opt-in."""

import argparse
import sys

from app.core.config import ConfigurationError, load_settings
from app.modules.executions.groq_provider import GroqError
from app.modules.workflows.evaluation import CASES, evaluate
from app.modules.workflows.generation import InvalidProposalError, generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Send selected synthetic prompts to configured Groq"
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=[case.id for case in CASES],
        help="Choose case; repeatable",
    )
    args = parser.parse_args()
    if not args.live:
        print("Add --live to send evaluation prompts to Groq. Available cases:")
        for case in CASES:
            print(f"  {case.id}")
        return 0
    try:
        settings = load_settings()
    except ConfigurationError:
        print("Invalid AgentFlow configuration.", file=sys.stderr)
        return 2
    if settings.groq_api_key is None or not settings.groq_api_key.get_secret_value().strip():
        print("Set GROQ_API_KEY before running live evaluations.", file=sys.stderr)
        return 2
    selected = [case for case in CASES if not args.case or case.id in args.case]
    print(f"Evaluating {len(selected)} synthetic cases with {settings.groq_model}.", flush=True)
    passed = 0
    for case in selected:
        try:
            proposal = generate(settings, case.prompt)
            outcome = evaluate(case, proposal)
            note = " (after regeneration)" if proposal.repair_attempted else ""
        except InvalidProposalError as error:
            outcome = "invalid_proposal:" + error.reason
            if error.issue_codes:
                outcome += ":" + ",".join(error.issue_codes)
            note = ""
        except GroqError as error:
            outcome = "rate_limited" if error.status == 429 else "provider_unavailable"
            note = ""
        passed += outcome == "pass"
        print(f"{case.id}: {outcome}{note}", flush=True)
        if outcome == "rate_limited":
            print("Stopping after provider rate limit; remaining cases were not run.")
            break
    print(f"Passed {passed}/{len(selected)} selected cases.")
    return 0 if passed == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
