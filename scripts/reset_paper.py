"""Remise a zero de l'etat paper trading (positions, ordres, trades, equity).

Usage: python scripts/reset_paper.py [--signals-date YYYY-MM-DD]
A utiliser uniquement avant le demarrage officiel du paper trading (jour 0);
toute remise a zero ulterieure invalide le track record (voir GO_LIVE.md).
"""

import argparse

from sqlalchemy import text

from atlas.data.store import init_db


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals-date", default=None,
                        help="supprime aussi les signaux de cette date")
    args = parser.parse_args()

    engine = init_db()
    with engine.begin() as conn:
        for table in ("positions", "orders", "trades", "paper_equity"):
            try:
                conn.execute(text(f"DELETE FROM {table}"))
            except Exception:
                pass  # table absente (paper_equity avant premier run)
        conn.execute(text("UPDATE paper_account SET cash=100000 WHERE id=1"))
        if args.signals_date:
            conn.execute(text("DELETE FROM signals WHERE as_of_date=:d"),
                         {"d": args.signals_date})
    print("etat paper remis a zero")


if __name__ == "__main__":
    main()
