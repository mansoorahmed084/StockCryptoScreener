"""Always-on alert scheduler (plan sec 4.12 / 5.3).

Runs a preset scan on an interval and fires de-duped alerts. Intended to run as a
small always-on service (VPS) so alerts arrive without the dashboard open.

    python -m backend.cli watch --interval 5
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from backend.alerts import AlertDispatcher, notifier_from_env
from backend.alerts.telegram import Notifier
from backend.config import Config, load_config
from backend.screener import filters as filters_mod
from backend.service import ScreenerService
from backend.signals.journal import SignalJournal

log = logging.getLogger(__name__)


def run_scan(config: Config, *, service: ScreenerService | None = None,
             journal: SignalJournal | None = None,
             notifier: Notifier | None = None,
             presets: list[str] | None = None,
             cooldown_s: float = 3600.0) -> list:
    """Build the matrix, evaluate presets and dispatch alerts once.

    Pass long-lived ``service``/``journal``/``notifier`` when calling repeatedly
    (the scheduler does) so connections are reused instead of leaked per tick.
    """
    svc = service if service is not None else ScreenerService(config)
    if service is not None:
        svc.adapter.refresh_markets()  # reused service: keep the market map fresh
    own_journal = journal is None
    jr = journal if journal is not None else SignalJournal()
    try:
        df = svc.build_matrix(liquidity_gate=True)
        disp = AlertDispatcher(jr, notifier or notifier_from_env(),
                               cooldown_s=cooldown_s)
        names = presets or list(filters_mod.PRESETS)
        fired = []
        for name in names:
            fired += disp.dispatch_preset(df, name, filters_mod.PRESETS[name]())
        log.info("scan fired %d alert(s)", len(fired))
        return fired
    finally:
        if own_journal:
            jr.close()


def start(interval_minutes: int = 5, *, config_path: str | None = None,
          presets: list[str] | None = None, cooldown_s: float = 3600.0) -> None:
    config = load_config(config_path)
    service = ScreenerService(config)
    journal = SignalJournal()
    notifier = notifier_from_env()
    scheduler = BlockingScheduler(timezone="UTC")

    def job():
        try:
            run_scan(config, service=service, journal=journal, notifier=notifier,
                     presets=presets, cooldown_s=cooldown_s)
        except Exception:  # keep the loop alive
            log.exception("scan job failed")

    # NOTE: do not pass next_run_time=None here — APScheduler 3.x treats that as
    # "add the job paused" and the interval would never fire.
    scheduler.add_job(job, "interval", minutes=interval_minutes)
    log.info("alert scheduler started: every %d min", interval_minutes)
    job()  # immediate first scan; the interval trigger handles the rest
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover
        log.info("scheduler stopped")
    finally:
        journal.close()
