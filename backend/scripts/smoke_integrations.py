"""Opt-in synthetic live checks; no database writes or business payload output."""

import argparse
from uuid import uuid4

from app.core.config import ConfigurationError, load_settings
from app.modules.connections.http_executor import get_json
from app.modules.connections.schemas import PlannerConnection
from app.modules.connections.service import AuthorizedConnection
from app.modules.executions.groq_provider import GroqError, complete
from app.modules.executions.operations import NodeExecutionError
from app.modules.workflows.generation import InvalidProposalError, generate

PUBLIC_ENDPOINT = "https://httpbin.org/json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly permit external requests")
    parser.add_argument("--http", action="store_true", help="GET the public httpbin JSON endpoint")
    parser.add_argument(
        "--groq", action="store_true", help="One synthetic configured Groq completion"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="One reviewed synthetic HTTP proposal (up to one repair)",
    )
    args = parser.parse_args(argv)
    if not args.live or not (args.http or args.groq or args.generate):
        print("No requests sent. Select --live and --http, --groq or --generate.")
        return 0
    if args.http:
        try:
            result = get_json(AuthorizedConnection(PUBLIC_ENDPOINT, "none"))
        except NodeExecutionError as error:
            print(f"http:{error.code.value}")
            return 1
        if result["status_code"] != 200 or not isinstance(result["body"], dict):
            print("http:unexpected_result")
            return 1
        print("http:passed (TLS, public DNS and bounded JSON)", flush=True)
    if args.groq or args.generate:
        try:
            settings = load_settings()
        except ConfigurationError:
            print("groq:invalid_configuration")
            return 2
        if settings.groq_api_key is None or not settings.groq_api_key.get_secret_value().strip():
            print("groq:not_configured (no provider request sent)")
            return 2
        try:
            if args.groq:
                result = complete(
                    settings,
                    "Reply with exactly the word Ready. This is a synthetic integration check.",
                )
                usage = result["metadata"].get("usage", {})
                print(
                    f"groq:passed total_tokens={usage.get('total_tokens', 'unreported')}",
                    flush=True,
                )
            if args.generate:
                selected = PlannerConnection(
                    id=uuid4(), name="Synthetic public JSON", endpoint_url=PUBLIC_ENDPOINT
                )
                proposal = generate(
                    settings,
                    "Create a manual workflow that uses the authorized HTTP GET connection "
                    "to read its fixed JSON endpoint, then ends with that result.",
                    connections=[selected],
                )
                if (
                    proposal.status != "ready"
                    or proposal.definition is None
                    or not any(
                        node.get("type") == "http"
                        and isinstance(config := node.get("config"), dict)
                        and config.get("connection_id") == str(selected.id)
                        for node in proposal.definition.nodes
                    )
                ):
                    print(f"generation:unexpected_proposal:status={proposal.status}")
                    return 1
                print(
                    f"generation:passed repair={proposal.repair_attempted} "
                    "(synthetic catalog; no workflow saved)",
                    flush=True,
                )
        except GroqError as error:
            print(f"groq:{error.code} (no automatic retry)")
            return 1
        except InvalidProposalError as error:
            codes = ",".join(error.issue_codes) if error.issue_codes else "none"
            print(f"generation:invalid_proposal:{error.reason}:codes={codes}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
