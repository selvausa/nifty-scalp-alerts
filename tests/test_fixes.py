"""Regression tests for the review findings."""
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from scalpbot.config import Rules, Settings
from scalpbot.groww import Groww, Inst
from scalpbot.indicators import add_indicators
from scalpbot.market import build_context
from scalpbot.options import Chain
from scalpbot.setups import Engine, Sizing
from scalpbot.telegram import Telegram
from tests.fakes import FakeOptions, flat_vix, random_days
from tests.test_runner import bot  # noqa: F401  (fixture)
from tests.test_setups import DAY, PREV, opt_break, orb_day, run


@pytest.fixture
def hist():
    h = random_days(PREV, seed=5, start=25030.0, vol=6.0)
    h.iloc[-40, h.columns.get_loc("h")] += 400
    h.iloc[-39, h.columns.get_loc("l")] -= 400
    return h


# 1 -------------------------------------------------------------------------
def test_failed_resolve_is_retried_same_day(monkeypatch):
    g = Groww(Settings(groww_access_token="t"))
    calls = {"n": 0}

    def resolve(today):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("instrument download failed")
        g.fut, g.expiry = Inst("NSE-NIFTY-FUT", "NIFTYFUT", "FNO", 65), "2026-11-17"

    monkeypatch.setattr("growwapi.GrowwAPI.__init__", lambda self, token: None)
    monkeypatch.setattr(g, "_resolve", resolve)
    with pytest.raises(RuntimeError):
        g.ensure(date(2026, 11, 16))
    g.ensure(date(2026, 11, 16))                 # must try again, not assume it is connected
    assert calls["n"] == 2 and g.fut is not None
    g.ensure(date(2026, 11, 16))
    assert calls["n"] == 2                       # once resolved, no more lookups that day
    g.ensure(date(2026, 11, 17))
    assert calls["n"] == 3                       # new day: log in again


# 2 -------------------------------------------------------------------------
class BrokenChain(FakeOptions):
    def chain(self):
        self.calls += 1
        raise TimeoutError("read timed out")


class NoGreeks(FakeOptions):
    def chain(self):
        self.calls += 1
        ch = self._chain
        return Chain(ch.spot, ch.expiry, {k: type(l)(l.strike, l.kind, l.symbol, l.ltp, 0.0) for k, l in ch.legs.items()})


@pytest.mark.parametrize("cls,why", [(BrokenChain, "timed out"), (NoGreeks, "no prices or deltas")])
def test_option_data_failure_keeps_chart_signal(hist, cls, why):
    day, _ = orb_day(hist)
    opt = cls(float(day["c"].iloc[-1]), opt_candles=opt_break(day))
    ctx, sigs, eng = run(day, hist, opt=opt)
    assert [s.setup for s in sigs] == ["B2"], eng.rejects
    unchecked = [c for c in sigs[0].checks if c.ok is None]
    assert unchecked and why in unchecked[0].detail
    assert opt.calls == 1                         # one attempt per candle, not one per setup


def test_sell_setup_survives_chain_failure(hist):
    from tests.test_setups import build_day, trend_day
    base, closes = trend_day(hist, 22)
    closes = closes + [closes[-1] + 4 * i for i in range(1, 9)] + [closes[-1] + 32 + i for i in range(1, 6)]
    day = build_day(closes)
    _, good, _ = run(day, hist)
    assert [s.setup for s in good] == ["S2"]      # the scenario fires with a working chain
    ctx, sigs, eng = run(day, hist, opt=BrokenChain(closes[-1]))
    assert [s.setup for s in sigs] == ["S2"], eng.rejects
    assert any(c.ok is None and "timed out" in c.detail for c in sigs[0].checks)


# 3, 7 ----------------------------------------------------------------------
class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self.ok, self._d, self.text = status, status == 200, data or {"ok": True, "result": []}, ""

    def json(self):
        return self._d


def test_backlog_commands_are_not_replayed(monkeypatch):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(dict(params))
        if params.get("offset") == -1:            # the stale message sent while the bot was down
            return Resp(data={"ok": True, "result": [{"update_id": 41, "message": {"chat": {"id": 7}, "text": "/taken"}}]})
        assert params.get("offset") == 42
        return Resp(data={"ok": True, "result": [{"update_id": 42, "message": {"chat": {"id": 7}, "text": "/status"}},
                                                 {"update_id": 43, "message": {"chat": {"id": 99}, "text": "/pause"}}]})

    monkeypatch.setattr("scalpbot.telegram.requests.get", get)
    tg = Telegram("tok", "7")
    assert tg.poll(5) == ["/status"]              # old /taken skipped; other chats ignored
    assert calls[0]["offset"] == -1 and tg.offset == 44


def test_backlog_check_failure_does_not_replay(monkeypatch):
    import requests

    def get(url, params=None, timeout=None):
        raise requests.ConnectionError("down")

    monkeypatch.setattr("scalpbot.telegram.requests.get", get)
    monkeypatch.setattr("scalpbot.telegram.time.sleep", lambda *_: None)
    tg = Telegram("tok", "7")
    assert tg.poll(5) == [] and tg.offset is None and not tg._drained


@pytest.mark.parametrize("statuses,expect,posts", [
    ([200], True, 1),
    ([400, 200], True, 2),          # bad markup: plain-text resend works
    ([400, 400], False, 2),         # wrong chat id: must not be reported as sent
    ([403], False, 1),
    ([500, 500, 200], True, 3),
])
def test_send_reports_real_outcome(monkeypatch, statuses, expect, posts):
    seen = []

    def post(url, timeout=None, json=None):
        seen.append(json)
        return Resp(statuses[len(seen) - 1])

    monkeypatch.setattr("scalpbot.telegram.requests.post", post)
    monkeypatch.setattr("scalpbot.telegram.time.sleep", lambda *_: None)
    assert Telegram("tok", "7").send("<b>x</b>") is expect
    assert len(seen) == posts
    if statuses[:2] == [400, 200]:
        assert "parse_mode" in seen[0] and "parse_mode" not in seen[1]


def test_unsent_alert_is_not_marked_sent(bot, tmp_path):
    b, close = bot
    b.tg.send = lambda text: False
    b.cycle(close)
    assert b.state.sent == {} and not (tmp_path / "alerts.csv").exists()


# 4 -------------------------------------------------------------------------
def test_spot_failure_warns_then_reuses_last_basis(bot):
    b, close = bot
    b.g.spot = lambda: None
    b.cycle(close)
    assert any("spot price unavailable" in m for m in b.tg.sent) and b.ctx.basis == 0.0
    b.g.spot = lambda: float(b.g.fut_df["c"].iloc[-1]) - 20.0
    b.cycle(close)
    assert b.ctx.basis == pytest.approx(20.0)
    b.g.spot = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    n = len(b.tg.sent)
    b.cycle(close)
    assert b.ctx.basis == pytest.approx(20.0)     # last known basis, not zero
    assert not any("spot price unavailable" in m for m in b.tg.sent[n:])


# 5, 9 ----------------------------------------------------------------------
class StubGroww(Groww):
    """Groww with the network replaced by a table of canned behaviour."""

    def __init__(self, fail=(), stale=()):
        super().__init__(Settings(groww_access_token="t"))
        self.fail, self.stale, self.log = set(fail), set(stale), []
        self.df = random_days([date(2026, 11, 12), date(2026, 11, 13)], seed=1)

    def _fetch(self, inst, start, end, mode):
        self.log.append((inst.groww_symbol or inst.trading_symbol, mode, start, end))
        if (inst.groww_symbol, mode) in self.fail:
            raise RuntimeError("endpoint error")
        df = self.df[(self.df.index >= pd.Timestamp(start)) & (self.df.index < pd.Timestamp(end))]
        return df.iloc[:-1] if (inst.groww_symbol, mode) in self.stale else df


FUT, VIX = Inst("FUT", "NIFTYFUT", "FNO"), Inst("VIX", "INDIAVIX", "CASH")
END = datetime(2026, 11, 13, 10, 0)


def test_endpoint_choice_is_per_instrument():
    g = StubGroww(fail={("VIX", "v2")})
    g.candles(VIX, END - timedelta(days=1), END)
    assert g.mode_for(VIX) == "legacy" and g.mode_for(FUT) == "v2"
    g.log.clear()
    g.candles(FUT, END - timedelta(days=1), END)
    assert [m for _, m, *_ in g.log] == ["v2"]    # the VIX problem did not move futures


def test_stale_endpoint_falls_back_for_latest_candle():
    need = pd.Timestamp("2026-11-13 09:55")
    g = StubGroww(stale={("FUT", "v2")})
    df = g.candles(FUT, END - timedelta(days=1), END, need)
    assert need in df.index and g.mode_for(FUT) == "legacy"


def test_no_fallback_without_the_symbol_it_needs():
    g = StubGroww(fail={("FUT", "v2")})
    with pytest.raises(RuntimeError):             # override gave only the Groww symbol
        g.candles(Inst("FUT", "", "FNO"), END - timedelta(days=1), END)
    assert [m for _, m, *_ in g.log] == ["v2"]
    g2 = StubGroww()
    g2.candles(Inst("", "NIFTYFUT", "FNO"), END - timedelta(days=1), END)
    assert [m for _, m, *_ in g2.log] == ["legacy"]
    fixed = StubGroww(fail={("FUT", "v2")})
    fixed.auto = False
    with pytest.raises(RuntimeError):             # CANDLE_API pinned: never switch
        fixed.candles(FUT, END - timedelta(days=1), END)


def test_history_fetched_once_per_day_and_result_unchanged():
    g = StubGroww()
    g.fut = FUT
    full = g.candles(FUT, END - timedelta(days=7), END)
    g.log.clear()
    a = g.fut_candles(END)
    b = g.fut_candles(END + timedelta(minutes=5))
    pd.testing.assert_frame_equal(a, full)        # identical to one big request
    assert len(b) == len(a) + 1
    hist_calls = [x for x in g.log if x[3] == datetime(2026, 11, 13)]
    today_calls = [x for x in g.log if x[2] == datetime(2026, 11, 13)]
    assert len(hist_calls) == 1 and len(today_calls) == 2
    g.log.clear()
    g.fut_candles(datetime(2026, 11, 14, 9, 20))  # next day: history is refreshed
    assert any(x[3] == datetime(2026, 11, 14) for x in g.log)


# 6 -------------------------------------------------------------------------
def test_taken_twice_counts_one_trade(bot):
    b, _ = bot
    b.command("/taken"); b.command("/taken")
    assert b.state.trades == 1 and "already" in b.tg.sent[-1]
    b.command("/flat"); b.command("/taken")
    assert b.state.trades == 2


# 8 -------------------------------------------------------------------------
def test_vix_fall_threshold_comes_from_rules(hist):
    day, _ = orb_day(hist)
    df = add_indicators(pd.concat([hist, day]))
    vix = flat_vix(df.index, 15.0)
    vix.iloc[-1, vix.columns.get_loc("c")] = 15.0 * 0.985          # -1.5% over 3 candles
    ts = day.index[-1]
    assert build_context(df, ts, vix, 3, []).vix_fall_sharp                       # default 1%
    assert not build_context(df, ts, vix, 3, [], vix_fall_pct=2.0).vix_fall_sharp
    assert build_context(df, ts, vix, 3, [], vix_fall_pct=Rules().vix_fall_sharp_pct).vix_fall_sharp


# 10 ------------------------------------------------------------------------
def test_range_used_property(hist):
    day, _ = orb_day(hist)
    ctx, _, _ = run(day, hist)
    assert ctx.range_used == pytest.approx(ctx.day_range / ctx.em)


# special sessions ------------------------------------------------------------
def test_short_special_session_is_not_the_previous_day(hist):
    """A one-hour Diwali muhurat session must not supply PDH/PDL/PDC."""
    day, _ = orb_day(hist)
    full = build_context(add_indicators(pd.concat([hist, day])), day.index[-1], None, 3, [])
    idx = pd.date_range("2026-11-12 13:45", periods=12, freq="5min")        # a short session after the last full day
    odd = pd.DataFrame({"o": 30000.0, "h": 30050.0, "l": 29950.0, "c": 30000.0, "v": 10.0}, index=idx)
    hist2 = pd.concat([hist[hist.index < "2026-11-12 13:45"], odd]).sort_index()
    hist2 = hist2[~((hist2.index.normalize() == "2026-11-12") & (hist2.index < "2026-11-12 13:45"))]
    ctx = build_context(add_indicators(pd.concat([hist2, day])), day.index[-1], None, 3, [])
    assert ctx.pdh < 29000 and ctx.pdc < 29000                               # taken from the last full session


def test_session_includes_candles_to_1540():
    from scalpbot.market import session_only
    idx = pd.date_range("2026-11-11 15:20", periods=8, freq="5min")          # 15:20 .. 15:55
    df = pd.DataFrame({"o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0}, index=idx)
    assert list(session_only(df).index.strftime("%H:%M")) == ["15:20", "15:25", "15:30", "15:35", "15:40"]
