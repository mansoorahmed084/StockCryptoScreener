from datetime import date

import pytest

from backend import smallcase_tracker as st

SH, MT, GI = "SCMO_0015", "SCTR_0008", "MF_118632"
TODAY = date(2026, 11, 1)


def _info(scid, index, last=None, nxt=None):
    return st.Info(scid, st.PORTFOLIO[scid][0], index,
                   {"1M": 0.01, "3M": 0.02, "1Y": 0.1, "3Y": 0.15, "5Y": 0.16}, last, nxt)


def _infos(sh=110.0, mt=100.0, gi=100.0, **kw):
    return {SH: _info(SH, sh, **kw), MT: _info(MT, mt, **kw), GI: _info(GI, gi, **kw)}


HIST = {s: {date(2026, 1, 1): 100.0, date(2026, 6, 1): 120.0} for s in (SH, MT, GI)}


def test_index_on_uses_last_point_on_or_before_the_day():
    h = HIST[SH]
    assert st.index_on(h, date(2026, 3, 1)) == 100.0
    assert st.index_on(h, date(2026, 6, 1)) == 120.0
    assert st.index_on(h, date(2025, 1, 1)) == 100.0   # older than history: first point


def test_value_units_times_today_index():
    buys = [st.Buy(date(2026, 1, 5), SH, 10_000), st.Buy(date(2026, 6, 5), SH, 12_000),
            st.Buy(date(2026, 1, 5), MT, 10_000)]
    lines = {l.scid: l for l in st.value(buys, _infos(sh=132.0), HIST)}
    # 100 units + 100 units at 132
    assert lines[SH].invested == 22_000
    assert lines[SH].value == pytest.approx(26_400)
    assert lines[MT].value == pytest.approx(10_000)
    assert lines[GI].value == 0
    assert sum(l.weight for l in lines.values()) == pytest.approx(1.0)


def test_unknown_scid_is_an_error():
    with pytest.raises(ValueError):
        st.value([st.Buy(date(2026, 1, 5), "XX_0001", 1000)], _infos(), HIST)


def test_split_fills_gaps_and_follows_targets_when_balanced():
    lines = [st.Line(SH, "a", 0, 10_000, 1 / 3), st.Line(MT, "b", 0, 10_000, 1 / 3),
             st.Line(GI, "c", 0, 10_000, 1 / 3)]
    for l in lines:
        l.weight = 1 / 3
    assert st.split(lines, 3000) == pytest.approx({SH: 1000, MT: 1000, GI: 1000})
    lines[0].value = 40_000          # SH far above target: it gets nothing
    s = st.split(lines, 30_000)
    assert s[SH] == 0
    assert s[MT] == pytest.approx(15_000) and s[GI] == pytest.approx(15_000)
    assert sum(s.values()) == pytest.approx(30_000)


def test_alerts_drift_and_sell_levels():
    buys = [st.Buy(date(2026, 1, 5), SH, 20_000), st.Buy(date(2026, 1, 5), MT, 10_000),
            st.Buy(date(2026, 1, 5), GI, 10_000)]
    lines = st.value(buys, _infos(sh=100.0), HIST)   # SH 50% vs 33.3%
    text = " ".join(st.alerts(lines, _infos(), TODAY))
    assert "Safe Haven Model** is 16.7 points above" in text
    assert "next SIP" in text
    assert "selling" in text


def test_alerts_rebalance_due_and_quiet_month():
    buys = [st.Buy(date(2026, 1, 5), s, 10_000) for s in (SH, MT, GI)]
    lines = st.value(buys, _infos(sh=100.0), HIST)
    due = st.alerts(lines, _infos(nxt=date(2026, 11, 5)), TODAY)
    assert len(due) == 3 and all("due on 05 Nov 2026" in a for a in due)
    quiet = st.alerts(lines, _infos(last=date(2026, 8, 1), nxt=date(2026, 12, 15)), TODAY)
    assert quiet[0].startswith("✅")


def test_render_and_write_markdown(tmp_path):
    md = tmp_path / "T.md"
    md.write_text("".join(f"<!-- AUTO:{n} -->\nstale text\n<!-- /AUTO:{n} -->\n"
                          for n in ("SUMMARY", "ALERTS", "MIX", "NEXT", "RETURNS")), encoding="utf-8")
    blocks = st.render(st.value([], _infos(), {}), _infos(), TODAY, 50_000)
    st.write_markdown(md, blocks)
    text = md.read_text(encoding="utf-8")
    assert "stale text" not in text and "No buys yet" in text
    assert "Rs 16,667" in text           # empty portfolio: the SIP follows the targets
    assert "+16.0%" in text               # 5Y CAGR column


def test_load_skips_blank_and_comment_rows(tmp_path):
    p = tmp_path / "b.csv"
    p.write_text("date,id,amount,note\n2026-11-03,SCMO_0015,15000,first\n"
                 "2026-11-03,MF_118632,15000,\n#2026-11-04,x,1,\n", encoding="utf-8")
    assert st.load(p) == [st.Buy(date(2026, 11, 3), SH, 15000.0), st.Buy(date(2026, 11, 3), GI, 15000.0)]
    old = tmp_path / "old.csv"     # the first version of the file called the column "scid"
    old.write_text("date,scid,amount,note\n2026-11-03,SCMO_0015,15000,\n", encoding="utf-8")
    assert st.load(old) == [st.Buy(date(2026, 11, 3), SH, 15000.0)]
    assert st.load(tmp_path / "missing.csv") == []


def test_mf_info_returns_from_nav_history():
    h = {date(2021, 10, 1): 50.0, date(2025, 10, 25): 80.0, date(2026, 9, 26): 90.0,
         date(2026, 10, 26): 100.0}
    i = st.mf_info(GI, h)
    assert i.index == 100.0 and i.name == st.PORTFOLIO[GI][0]
    assert i.returns["1M"] == pytest.approx(100 / 90 - 1)
    assert i.returns["1Y"] == pytest.approx(0.25)
    assert i.returns["5Y"] == pytest.approx(2 ** (1 / 5) - 1)
    assert i.last_rebalance is None and i.next_rebalance is None
    short = st.mf_info(GI, {date(2026, 1, 1): 10.0, date(2026, 10, 26): 11.0})
    assert short.returns["3Y"] is None and short.returns["5Y"] is None
