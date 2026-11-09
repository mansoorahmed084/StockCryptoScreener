"""The desk's jobs: night, morning and tick, and the loop that runs them.

  night    backtest every rule (keep / kill) + read the news
  morning  screen the watchlist + write trade plans for kept rules
  tick     paper trades (fills, stops, targets) + price alerts

``watch`` runs tick every few minutes, and night and morning once a day at
the IST times in desk.yaml. Start it late and it catches up at once.
"""
from __future__ import annotations

import datetime as dt
import logging
import time

from . import alerts, heatmap, news, paper
from .backtest import run_backtests
from .data import DeskData
from .notify import Sender, morning_card, night_card
from .plans import kept_rules, make_plans
from .screen import run_screen
from .settings import Settings
from .store import DeskStore

log = logging.getLogger(__name__)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class Desk:
    def __init__(self, settings: Settings | None = None, data: DeskData | None = None,
                 store: DeskStore | None = None, sender: Sender | None = None):
        self.settings = settings or Settings.load()
        self.data = data or DeskData(cache_dir=self.settings.cache_dir)
        self.store = store or DeskStore(self.settings.db_target)
        self.sender = sender if sender is not None else Sender(self.settings)

    def _stamp(self, key: str) -> None:
        self.store.set_meta(f"last_{key}", str(int(time.time())))

    def backtest(self, now: float | None = None) -> list[dict]:
        verdicts, per_symbol = run_backtests(self.settings, self.data, now)
        self.store.save_backtest(int(time.time()), verdicts, per_symbol)
        self._stamp("backtest")
        return verdicts

    def research(self, now: float | None = None) -> dict:
        out = news.research(self.settings, self.data, self.store, now)
        self._stamp("research")
        return out

    def night(self, notify: bool = True) -> dict:
        verdicts = self.backtest()
        res = self.research()
        if notify:
            self.sender.send(night_card(verdicts, res["spikes"], res["fear_greed"]))
        self._stamp("night")
        return {"verdicts": verdicts, **res}

    def morning(self, notify: bool = True) -> dict:
        verdicts = self.store.latest_verdicts()
        if not verdicts:                       # first run: test the rules first
            verdicts = self.backtest()
        rows = run_screen(self.settings, self.data)
        self.store.save_screen(int(time.time()), rows)
        plans = make_plans(self.settings, self.data, self.store, rows, verdicts)
        if notify:
            self.sender.send(morning_card(rows, plans, kept_rules(verdicts)))
        self._stamp("morning")
        return {"screen": rows, "plans": plans, "verdicts": verdicts}

    def tick(self) -> list[paper.Event]:
        events = paper.tick(self.settings, self.data, self.store, self.sender)
        symbols = sorted(set(self.settings.watch_all())
                         | {p["symbol"] for p in self.store.plans("pending")}
                         | {t["symbol"] for t in self.store.trades("open")}
                         | {a["symbol"] for a in self.store.alerts(active=True)})
        quotes = None
        try:
            quotes = self.data.quotes(symbols)
            self.store.save_quotes(quotes)
        except Exception as exc:   # alerts fetch again on their own
            log.warning("desk quotes failed: %s", exc)
        events += alerts.check(self.store, self.data, self.sender, quotes)
        self.refresh_heatmap()
        self._stamp("tick")
        return events

    def refresh_heatmap(self, max_age: int = 900) -> bool:
        """Save the heatmap for the cloud page, at most every ``max_age`` s."""
        last = int(self.store.get_meta("heatmap_ts") or 0)
        if time.time() - last < max_age:
            return False
        try:
            df = heatmap.build(self.settings, self.data)
        except Exception as exc:
            log.warning("desk heatmap failed: %s", exc)
            return False
        if df.empty:
            return False
        now = int(time.time())
        self.store.save_heatmap(now, df.to_dict("records"))
        self.store.set_meta("heatmap_ts", str(now))
        return True

    def watch(self, interval_min: float | None = None) -> None:
        sched = self.settings.section("schedule")
        interval = float(interval_min or sched.get("tick_minutes", 5)) * 60
        night_at, morning_at = str(sched.get("night", "03:00")), str(sched.get("morning", "08:45"))
        log.info("desk watch: tick every %.0f s, night %s IST, morning %s IST",
                 interval, night_at, morning_at)
        while True:
            ist = dt.datetime.now(IST)
            today, hhmm = ist.date().isoformat(), ist.strftime("%H:%M")
            for job, at in (("night", night_at), ("morning", morning_at)):
                if hhmm >= at and self.store.get_meta(f"{job}_date") != today:
                    try:
                        getattr(self, job)()
                        self.store.set_meta(f"{job}_date", today)
                    except Exception:
                        log.exception("desk %s failed", job)
            try:
                for ev in self.tick():
                    log.info("desk %s %s", ev.kind, ev.symbol)
            except Exception:
                log.exception("desk tick failed")
            time.sleep(interval)
