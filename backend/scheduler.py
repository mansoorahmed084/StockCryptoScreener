"""Always-on alert scheduler (plan sec 4.12 / 5.3).

Runs a preset scan on an interval and fires de-duped alerts. Intended to run as a
small always-on service (VPS) so alerts arrive without the dashboard open.

    python -m backend.cli watch --interval 5
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from backend.alerts import AlertDispatcher, notifier_from_env
from backend.config import Config, load_config
from backend.screener import filters as filters_mod
from backend.service import ScreenerService
from backend.signals.journal import SignalJournal

log = logging.getLogger(__name__)


def run_scan(config: Config, *, presets: list[str] | None = None,
             cooldown_s: float = 3600.0) -> list:
    """Build the matrix, evaluate presets and dispatch alerts once."""
    svc = ScreenerService(config)
    df = svc.build_matrix(liquidity_gate=True)
    disp = AlertDispatcher(SignalJournal(), notifier_from_env(),
                           cooldown_s=cooldown_s)
    names = presets or list(filters_mod.PRESETS)
    fired = []
    for name in names:
        flt = filters_mod.PRESETS[name]()
        fired += disp.dispatch_preset(df, name, flt)
    log.info("scan fired %d alert(s)", len(fired))
    return fired


def start(interval_minutes: int = 5, *, config_path: str | None = None,
          presets: list[str] | None = None, cooldown_s: float = 3600.0) -> None:
    config = load_config(config_path)
    scheduler = BlockingScheduler(timezone="UTC")

    def job():
        try:
            run_scan(config, presets=presets, cooldown_s=cooldown_s)
        except Exception:  # keep the loop alive
            log.exception("scan job failed")

    scheduler.add_job(job, "interval", minutes=interval_minutes,
                      next_run_time=None)
    log.info("alert scheduler started: every %d min", interval_minutes)
    job()  # run once immediately
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover
        log.info("scheduler stopped")
