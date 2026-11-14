"""End-to-end: one cycle of the live loop against a fake Groww and a captured Telegram."""
from datetime import datetime

import pandas as pd
import pytest

from scalpbot.config import Settings
from scalpbot.runner import Bot, next_boundary
from tests.fakes import FakeOptions, flat_vix, random_days
from tests.test_setups import DAY, PREV, opt_break, orb_day


class FakeTG:
    enabled = True

    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        return True


class FakeGroww:
    lot_size = 65
    mode = "v2"

    def __init__(self, fut, opt, dte=3):
        self.fut_df, self.opt, self._dte, self.chain_calls = fut, opt, dte, 0

    def ensure(self, today): pass
    def dte(self, today): return self._dte
    def fut_candles(self, end, need=None, days=7): return self.fut_df[self.fut_df.index < pd.Timestamp(end)]
    def vix_candles(self, end, days=7): return flat_vix(self.fut_df.index, 15.0)
    def spot(self): return float(self.fut_df["c"].iloc[-1]) - 20.0
    def chain(self): return self.opt.chain()
    def fill_quote(self, leg): return self.opt.fill_quote(leg)
    def option_candles(self, leg): return self.opt.candles(leg)


@pytest.fixture
def bot(tmp_path, monkeypatch):
    hist = random_days(PREV, seed=5, start=25030.0, vol=6.0)
    hist.iloc[-40, hist.columns.get_loc("h")] += 400
    hist.iloc[-39, hist.columns.get_loc("l")] -= 400
    day, _ = orb_day(hist)
    fut = pd.concat([hist, day])
    opt = FakeOptions(float(day["c"].iloc[-1]) - 20.0, opt_candles=opt_break(day))
    s = Settings(capital=500000, data_dir=tmp_path, events_file=tmp_path / "none.txt")
    close = (day.index[-1] + pd.Timedelta(minutes=5)).to_pydatetime()
    monkeypatch.setattr("scalpbot.runner.ist_now", lambda: close)
    monkeypatch.setattr("scalpbot.runner._time.sleep", lambda *_: None)
    b = Bot(s, groww=FakeGroww(fut, opt), tg=FakeTG())
    return b, close


def test_cycle_sends_alert_once_and_logs(bot, tmp_path):
    b, close = bot
    b.cycle(close)
    alerts = [m for m in b.tg.sent if "Opening-range breakout" in m]
    assert len(alerts) == 1 and "BUY CE" in alerts[0] and "Strike:" in alerts[0]
    rows = (tmp_path / "alerts.csv").read_text().splitlines()
    assert len(rows) == 2 and rows[1].split(",")[1] == "B2"
    b.cycle(close)                                   # same candle again: no duplicate
    assert len([m for m in b.tg.sent if "Opening-range breakout" in m]) == 1


def test_open_position_and_limits_suppress_alerts(bot):
    b, close = bot
    b.command("/taken")
    assert "trade 1 of 4" in b.tg.sent[-1] and "OFF" in b.tg.sent[-1]
    b.cycle(close)
    assert not [m for m in b.tg.sent if "Opening-range breakout" in m]
    b.command("/loss 1200")
    assert "P&amp;L ₹-1,200" in b.tg.sent[-1] or "₹-1,200" in b.tg.sent[-1]
    b.command("/pause")
    b.cycle(close)
    assert not [m for m in b.tg.sent if "Opening-range breakout" in m]
    b.command("/resume")
    b.cycle(close)
    assert [m for m in b.tg.sent if "Opening-range breakout" in m]
    b.command("/status"); b.command("/brief"); b.command("/help"); b.command("/nonsense")
    assert "Unknown command" in b.tg.sent[-1]


def test_missing_candle_is_skipped_quietly(bot):
    b, close = bot
    later = close + pd.Timedelta(minutes=5)
    b.cycle(later.to_pydatetime() if hasattr(later, "to_pydatetime") else later)
    assert not [m for m in b.tg.sent if "breakout" in m] and b.miss == 1


def test_errors_are_reported_not_fatal(bot):
    b, close = bot
    b.g.fut_candles = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    b.safely(b.cycle, close)
    assert "boom" in b.tg.sent[-1]


def test_next_boundary():
    assert next_boundary(datetime(2026, 11, 13, 9, 47, 31)) == datetime(2026, 11, 13, 9, 50)
    assert next_boundary(datetime(2026, 11, 13, 9, 50, 0)) == datetime(2026, 11, 13, 9, 55)
