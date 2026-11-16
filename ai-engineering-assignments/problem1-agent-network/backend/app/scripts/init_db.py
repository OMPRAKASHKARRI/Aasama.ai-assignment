"""Create the database schema:  python -m app.scripts.init_db   (runs `alembic upgrade head`)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")
    print("database schema is up to date")


if __name__ == "__main__":
    main()
