"""Install/update the maintained agent checkpoint schema without changing application history."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_settings  # noqa: E402
from app.infrastructure.database.session import Database  # noqa: E402
from app.modules.agents.checkpoints import setup_checkpoints  # noqa: E402


def main() -> int:
    settings = load_settings()
    if settings.database_url is None:
        print("Configure the database before checkpoint setup.", file=sys.stderr)
        return 1
    database = Database(settings.database_url)
    try:
        setup_checkpoints(database)
    except Exception:
        print(
            "Checkpoint setup failed; verify database access and schema permissions.",
            file=sys.stderr,
        )
        return 1
    finally:
        database.dispose()
    print("Agent checkpoint schema is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
