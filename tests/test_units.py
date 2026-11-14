from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from scalpbot import indicators as ind
from scalpbot.config import Rules, load_events
from scalpbot.groww import parse_candles, parse_chain, parse_quote
from scalpbot.market import expected_move
from scalpbot.options import (buy_spread_ok, legs_liquid, pick_buy, pick_credit_spread,
                              sell_delta_range)
from scalpbot.state import DayState
from tests.fakes import make_chain, random_days

D = [date(2026, 11, 11), date(2026, 11, 12), date(2026, 11, 13)]


def test_rsi_extremes_and_atr():
    idx = pd.date_range("2026-11-13 09:15", periods=60, freq="5min")
    up = pd.Series(np.arange(60, dtype=float) + 100, index=idx)
    assert ind.rsi(up).iloc[-1] > 99 or np.isnan(ind.rsi(up).iloc[-1])  # no losses at all
    df = pd.DataFrame({"o": 100.0, "h": 105.0, "l": 95.0, "c": 100.0, "v": 1.0}, index=idx)
    assert ind.atr(df).iloc[-1] == pytest.approx(10.0)
    assert ind.adx(df).iloc[-1] == pytest.approx(0.0)


def test_adx_high_in_trend_low_in_chop():
    trend = ind.add_indicators(random_days(D, seed=1, vol=4, drift=6))
    chop = ind.add_indicators(random_days(D, seed=1, vol=10, drift=0))
    assert trend["adx"].iloc[-1] > 40 > chop["adx"].iloc[-1]


def test_vwap_resets_each_session():
    df = ind.add_indicators(random_days(D, seed=2))
    first = df[df.index.normalize() == pd.Timestamp(D[2])].iloc[0]
    assert first["vwap"] == pytest.approx((first["h"] + first["l"] + first["c"]) / 3)
    assert first["vwap_sd"] == pytest.approx(0.0, abs=0.01)
    day = df[df.index.normalize() == pd.Timestamp(D[2])]
    tp = (day["h"] + day["l"] + day["c"]) / 3
    assert day["vwap"].iloc[-1] == pytest.approx((tp * day["v"]).sum() / day["v"].sum())


def test_15m_only_closed_candles():
    df = random_days(D[:1], seed=3)
    m = ind.to_15m(df, pd.Timestamp("2026-11-11 09:40"))   # 09:30 candle is still forming
    assert list(m.index) == [pd.Timestamp("2026-11-11 09:15")]
    assert m["h"].iloc[0] == df["h"].iloc[:3].max() and m["c"].iloc[0] == df["c"].iloc[2]


def test_expected_move_matches_sheet():
    assert expected_move(25150, 15.5) == pytest.approx(245, abs=1)


def test_parse_candles_formats():
    a = parse_candles({"candles": [[1794541500, 1, 2, 0.5, 1.5, 10], [1794541800000, 2, 3, 1, 2, None]]})
    assert a.index[1] - a.index[0] == pd.Timedelta(minutes=5) and a["v"].iloc[1] == 0
    assert a.index[0] == pd.Timestamp(1794541500 + 19800, unit="s")     # epoch shown in IST
    b = parse_candles({"candles": [["2026-11-13T09:15:00", 1, 2, 0.5, 1.5, 10, 99]]})
    assert b.index[0] == pd.Timestamp("2026-11-13 09:15") and b["c"].iloc[0] == 1.5
    assert parse_candles({}).empty


def test_parse_chain_and_quote():
    ch = parse_chain({"underlying_ltp": 25150.4, "strikes": {"25150": {
        "CE": {"trading_symbol": "NIFTY26N1725150CE", "ltp": 120.5, "greeks": {"delta": 0.52}},
        "PE": {"trading_symbol": "NIFTY26N1725150PE", "ltp": 110.0, "greeks": {"delta": -0.48}}}}}, "2026-11-17")
    assert ch.spot == 25150.4 and ch.get(25150, "PE").delta == -0.48
    assert ch.atm_straddle() == pytest.approx(230.5)
    assert parse_quote({"bid_price": 120.1, "offer_price": 120.4, "last_price": 120.3}) == (120.1, 120.4, 120.3)
    assert parse_quote({"depth": {"buy": [{"price": 5.0}], "sell": [{"price": 5.2}]}})[:2] == (5.0, 5.2)
    assert parse_quote({}) == (None, None, None)


def test_strike_selection():
    ch, r = make_chain(25160), Rules()
    for dte, (lo, hi) in ((3, (0.45, 0.55)), (1, (0.50, 0.65)), (0, (0.60, 0.80))):
        ce, pe = pick_buy(ch, 1, dte), pick_buy(ch, -1, dte)
        assert ce.kind == "CE" and lo <= ce.delta <= hi
        assert pe.kind == "PE" and lo <= -pe.delta <= hi
    assert pick_buy(ch, 1, 0).strike < 25160            # expiry day is in the money
    sp = pick_credit_spread(ch, "PE", 25100, sell_delta_range("S2", 3), r)
    assert sp.short.strike < 25100 and sp.hedge.strike == sp.short.strike - 100
    assert 0.15 <= -sp.short.delta <= 0.30 and sp.credit > 0
    cs = pick_credit_spread(ch, "CE", 25250, sell_delta_range("S1", 0), r)
    assert cs.short.strike > 25250 and cs.hedge.strike == cs.short.strike + 100
    assert pick_credit_spread(ch, "PE", 20000, (0.15, 0.30), r) is None


def test_liquidity_rules():
    ch, r = make_chain(25160), Rules()
    leg = pick_buy(ch, 1, 3)
    assert buy_spread_ok(leg, r) is None                # no quote yet
    leg.bid, leg.ask = leg.ltp - 0.1, leg.ltp + 0.1
    assert buy_spread_ok(leg, r) is True
    leg.bid, leg.ask = leg.ltp - 0.4, leg.ltp + 0.4     # 0.80 wide
    assert buy_spread_ok(leg, r) is False
    cheap = ch.get(25400, "CE"); cheap.bid, cheap.ask = cheap.ltp, cheap.ltp + 0.10
    assert legs_liquid([cheap], r) is True
    cheap.ask = cheap.bid + 0.20
    assert legs_liquid([cheap], r) is False


def test_state_limits_and_dedupe(tmp_path):
    r, p = Rules(), tmp_path / "state.json"
    st = DayState.load(p, date(2026, 11, 13))
    assert st.blocked(r, 500000) is None
    st.position_open = True
    assert "position" in st.blocked(r, 500000)
    st.position_open, st.consec_losses = False, 3
    assert "consecutive" in st.blocked(r, 500000)
    st.consec_losses, st.pnl = 0, -10000
    assert "loss limit" in st.blocked(r, 500000) and st.blocked(r, 0) is None
    st.pnl, st.trades = 0, 4
    assert "trades" in st.blocked(r, 500000)
    t = datetime(2026, 11, 13, 10, 20)
    st.mark_sent("B1:1", t); st.mark_sent("B2:1", t)
    assert not st.can_send("B1:1", t.replace(minute=45), 30) and st.can_send("B1:1", t.replace(minute=50), 30)
    assert not st.can_send("B2:1", t.replace(hour=14), 30)      # once per day
    st.paused = True
    st.save(p)
    assert DayState.load(p, date(2026, 11, 13)).trades == 4
    nxt = DayState.load(p, date(2026, 11, 16))
    assert nxt.trades == 0 and nxt.sent == {} and nxt.paused    # pause survives the day roll


def test_events_file(tmp_path):
    f = tmp_path / "e.txt"
    f.write_text("# c\n2026-12-04 10:00 RBI policy\n2027-02-01 Union Budget\nbad line\n")
    ev = load_events(f)
    assert [(e.day.isoformat(), e.at and e.at.hour, e.name) for e in ev] == [
        ("2026-12-04", 10, "RBI policy"), ("2027-02-01", None, "Union Budget")]
