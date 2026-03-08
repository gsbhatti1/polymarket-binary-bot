from decimal import Decimal
from pathlib import Path

from polymarket_bot.runner import run_loop


def test_replay_loop_runs_n_ticks(tmp_path: Path):
    """Runner should complete N ticks in replay mode without error."""
    db_path = (tmp_path / "bot.db").as_posix()
    run_loop(
        mode="replay",
        db_path=db_path,
        markets=["BTC_UP"],
        max_ticks=5,
        prior=Decimal("0.60"),
    )

    # Verify DB was populated
    from polymarket_bot.db import Database
    db = Database(db_path)
    assert db.count_rows("runs") >= 1
    assert db.count_rows("orders") >= 1  # at least one trade on first tick
    db.close()
