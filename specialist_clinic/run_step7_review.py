"""Start an isolated local review instance for the final Clinical Engine UI."""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5057)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    review_dir = root / "instance" / "step7-review"
    review_dir.mkdir(parents=True, exist_ok=True)
    database = review_dir / "clinic-step7-review.db"
    if args.reset and database.exists():
        database.unlink()

    os.environ["SPECIALIST_DB_PATH"] = str(database)
    os.environ.setdefault("SECRET_KEY", "local-step7-review-only")
    os.environ.setdefault("DEBUG", "1")

    from src.app import create_app

    app = create_app()
    print(f"Step 7 review: http://{args.host}:{args.port}/manager/clinical-engine/validation")
    print("Development login: admin / admin")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
