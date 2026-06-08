"""
Universe Scanner — dynamic daily/weekly stock discovery.

Sources (in priority order):
  1. Seed universe (config.TIER_1 + TIER_2 + TIER_3)
  2. SMALL_CAP_WATCHLIST (filtered by liquidity)
  3. Alpaca movers: top_gainers, top_losers, most_actives

Output: two timeframe-keyed lists with directional bias hints:
  - intraday: 5-min strategies (EMA_VWAP, ORB, shorts) — refreshed daily 9:10am
  - swing:    daily strategies (RSI_BOUNCE long, RSI_FADE short) — refreshed weekly

Each symbol carries a `tier` ("large"/"mid"/"small") that risk_manager
uses for position sizing, and a `bias` hint:
  - "long_pullback"  — top loser, oversold candidate
  - "long_momentum"  — most active, no extreme direction
  - "short_fade"     — top gainer, exhaustion candidate
  - "neutral"        — seed universe, no directional read

Top gainers do NOT auto-become long candidates — the long strategies'
extension filters will reject already-extended names. The bias hint
just tells the selector which strategy to *try first*.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import config
from logger_setup import get_logger
from utils import now_et


_CACHE_FILE = Path(__file__).parent / config.DATA_DIR / "universe_cache.json"


def _classify_tier(symbol: str, price: Optional[float] = None) -> str:
    """Heuristic tier classification. Lower tier => smaller position size."""
    if symbol in config.TIER_1:
        return "large"
    if symbol in config.TIER_2 or symbol in config.TIER_3:
        return "large" if symbol in ("SPY", "QQQ") else "mid"
    if symbol in config.SMALL_CAP_WATCHLIST:
        return "small"
    # Movers we don't recognise: classify by price as a proxy
    if price is not None and price < 20.0:
        return "small"
    return "mid"


class UniverseScanner:
    """Discovers tradable universe per timeframe + caches results."""

    def __init__(self, api):
        self.api = api
        self.log = get_logger()
        # symbol -> {tier, bias, source, price}
        self.intraday: Dict[str, dict] = {}
        self.swing: Dict[str, dict] = {}
        self._intraday_refreshed_at: Optional[datetime] = None
        self._swing_refreshed_at: Optional[datetime] = None
        self._load_cache()

    # ─── Public ─────────────────────────────────────────────────────────

    def intraday_symbols(self) -> List[str]:
        return list(self.intraday.keys())

    def swing_symbols(self) -> List[str]:
        return list(self.swing.keys())

    def all_symbols(self) -> List[str]:
        return list({*self.intraday.keys(), *self.swing.keys()})

    def meta(self, symbol: str) -> dict:
        """Return {tier, bias, source} for a symbol (with safe defaults)."""
        return (self.intraday.get(symbol)
                or self.swing.get(symbol)
                or {"tier": _classify_tier(symbol), "bias": "neutral", "source": "fallback"})

    def tier(self, symbol: str) -> str:
        return self.meta(symbol).get("tier", "mid")

    def bias(self, symbol: str) -> str:
        return self.meta(symbol).get("bias", "neutral")

    # ─── Refresh ────────────────────────────────────────────────────────

    def refresh_intraday(self):
        """Rebuild the intraday universe. Call once at market-open prep."""
        self.log.info("Universe: refreshing intraday list...")
        candidates: Dict[str, dict] = {}

        # 1. Seed universe — always present
        for sym in config.TIER_1 + config.TIER_2 + config.TIER_3:
            candidates[sym] = {"tier": _classify_tier(sym), "bias": "neutral",
                               "source": "seed", "price": None}

        # 2. Small-cap watchlist
        for sym in config.SMALL_CAP_WATCHLIST:
            candidates.setdefault(sym, {"tier": "small", "bias": "neutral",
                                        "source": "small_cap_watchlist", "price": None})

        # 3. Alpaca movers (gainers → short_fade, losers → long_pullback,
        #    most_actives → long_momentum)
        movers = self._fetch_movers()
        for sym, m in movers.get("gainers", {}).items():
            candidates.setdefault(sym, {"tier": _classify_tier(sym, m.get("price")),
                                        "bias": "short_fade",
                                        "source": "alpaca_top_gainer",
                                        "price": m.get("price")})
            # If already in seed but a big gainer, override bias hint
            if candidates[sym]["bias"] == "neutral":
                candidates[sym]["bias"] = "short_fade"

        for sym, m in movers.get("losers", {}).items():
            candidates.setdefault(sym, {"tier": _classify_tier(sym, m.get("price")),
                                        "bias": "long_pullback",
                                        "source": "alpaca_top_loser",
                                        "price": m.get("price")})
            if candidates[sym]["bias"] == "neutral":
                candidates[sym]["bias"] = "long_pullback"

        for sym, m in movers.get("most_actives", {}).items():
            candidates.setdefault(sym, {"tier": _classify_tier(sym, m.get("price")),
                                        "bias": "long_momentum",
                                        "source": "alpaca_most_active",
                                        "price": m.get("price")})

        # 4. Liquidity / price filter
        filtered = self._apply_liquidity_filter(candidates)

        # 5. Cap size
        if len(filtered) > config.UNIVERSE_DAILY_MAX:
            # Keep all seeds + small-caps, then fill with movers
            seeds = {s: filtered[s] for s in filtered
                     if filtered[s]["source"] in ("seed", "small_cap_watchlist")}
            movers_only = {s: filtered[s] for s in filtered if s not in seeds}
            remaining = config.UNIVERSE_DAILY_MAX - len(seeds)
            if remaining > 0:
                # Take movers sorted by abs price (most extreme moves first if available)
                mover_syms = list(movers_only.keys())[:remaining]
                filtered = {**seeds, **{s: movers_only[s] for s in mover_syms}}
            else:
                filtered = dict(list(seeds.items())[:config.UNIVERSE_DAILY_MAX])

        # If movers were empty AND a richer cache already exists, keep the cache
        # rather than degrading to seed-only (happens when Alpaca screener API
        # rate-limits or auth fails on the data host).
        mover_count = sum(1 for v in filtered.values() if v["source"].startswith("alpaca"))
        if mover_count == 0 and len(self.intraday) > len(filtered):
            self.log.warning(
                f"Universe: mover fetch returned 0 — keeping existing cache "
                f"of {len(self.intraday)} symbols instead of degrading to {len(filtered)} seeds"
            )
            return

        self.intraday = filtered
        self._intraday_refreshed_at = now_et()
        self._save_cache()
        self.log.info(
            f"Universe: intraday list has {len(self.intraday)} symbols "
            f"(small={sum(1 for v in self.intraday.values() if v['tier']=='small')}, "
            f"mover-sourced={sum(1 for v in self.intraday.values() if v['source'].startswith('alpaca'))})"
        )

    def refresh_swing(self):
        """Rebuild the swing universe. Call weekly (Mon pre-market)."""
        self.log.info("Universe: refreshing swing list...")
        candidates: Dict[str, dict] = {}

        # Swing = seed large/mid + watchlist (NO mover-only — too noisy weekly)
        for sym in config.TIER_1 + config.TIER_2 + config.TIER_3:
            candidates[sym] = {"tier": _classify_tier(sym), "bias": "neutral",
                               "source": "seed", "price": None}
        for sym in config.SMALL_CAP_WATCHLIST:
            candidates.setdefault(sym, {"tier": "small", "bias": "neutral",
                                        "source": "small_cap_watchlist", "price": None})

        # Add today's top losers as oversold-bounce candidates
        movers = self._fetch_movers()
        for sym, m in movers.get("losers", {}).items():
            candidates.setdefault(sym, {"tier": _classify_tier(sym, m.get("price")),
                                        "bias": "long_pullback",
                                        "source": "alpaca_top_loser",
                                        "price": m.get("price")})

        # Add top gainers for RSI_FADE shorts
        for sym, m in movers.get("gainers", {}).items():
            candidates.setdefault(sym, {"tier": _classify_tier(sym, m.get("price")),
                                        "bias": "short_fade",
                                        "source": "alpaca_top_gainer",
                                        "price": m.get("price")})

        filtered = self._apply_liquidity_filter(candidates)

        if len(filtered) > config.UNIVERSE_SWING_MAX:
            filtered = dict(list(filtered.items())[:config.UNIVERSE_SWING_MAX])

        self.swing = filtered
        self._swing_refreshed_at = now_et()
        self._save_cache()
        self.log.info(f"Universe: swing list has {len(self.swing)} symbols")

    # ─── Internals ──────────────────────────────────────────────────────

    def _fetch_movers(self) -> dict:
        """
        Hit Alpaca's screener endpoints. The Python SDK (alpaca-trade-api)
        doesn't expose these directly, so we go through `_request` if
        available, else fall back to {}.

        Returns dict keyed by category: {gainers, losers, most_actives}.
        Each value is {symbol: {price, change_pct}}.
        """
        result = {"gainers": {}, "losers": {}, "most_actives": {}}
        try:
            # Try Alpaca market-data v1beta1 screener (data API host)
            # The SDK's `data` connection has _one_request; fall through
            # gracefully if unavailable.
            base = "https://data.alpaca.markets/v1beta1/screener/stocks"
            for cat, key in [("movers", None)]:
                try:
                    resp = self.api._data_get(
                        f"/v1beta1/screener/stocks/movers",
                        data={"top": 25},
                    )
                except Exception:
                    resp = None
                if resp:
                    for r in resp.get("gainers", []):
                        s = r.get("symbol")
                        if s:
                            result["gainers"][s] = {
                                "price": float(r.get("price", 0) or 0),
                                "change_pct": float(r.get("percent_change", 0) or 0),
                            }
                    for r in resp.get("losers", []):
                        s = r.get("symbol")
                        if s:
                            result["losers"][s] = {
                                "price": float(r.get("price", 0) or 0),
                                "change_pct": float(r.get("percent_change", 0) or 0),
                            }
                # Most actives
                try:
                    resp2 = self.api._data_get(
                        f"/v1beta1/screener/stocks/most-actives",
                        data={"top": 25},
                    )
                except Exception:
                    resp2 = None
                if resp2:
                    for r in resp2.get("most_actives", []):
                        s = r.get("symbol")
                        if s:
                            result["most_actives"][s] = {
                                "price": float(r.get("price", 0) or 0),
                                "change_pct": 0.0,
                            }
        except Exception as e:
            self.log.warning(f"Mover fetch failed (continuing with seed only): {e}")

        n = sum(len(v) for v in result.values())
        self.log.info(f"Universe: pulled {n} mover symbols from Alpaca screener")
        return result

    def _apply_liquidity_filter(self, candidates: Dict[str, dict]) -> Dict[str, dict]:
        """
        Filter candidates by price band + average dollar-volume.
        We can't easily get ADV without bar history, so for symbols
        without a known price we ASSUME they pass (the bar-download
        step in main.py will weed out anything truly untradable).
        """
        out = {}
        for sym, meta in candidates.items():
            price = meta.get("price")
            if price is not None and price > 0:
                if price < config.UNIVERSE_MIN_PRICE or price > config.UNIVERSE_MAX_PRICE:
                    self.log.debug(f"  drop {sym}: price ${price:.2f} out of band")
                    continue
            out[sym] = meta
        return out

    # ─── Cache ──────────────────────────────────────────────────────────

    def _save_cache(self):
        try:
            _CACHE_FILE.parent.mkdir(exist_ok=True)
            payload = {
                "intraday": self.intraday,
                "swing": self.swing,
                "intraday_at": self._intraday_refreshed_at.isoformat() if self._intraday_refreshed_at else None,
                "swing_at": self._swing_refreshed_at.isoformat() if self._swing_refreshed_at else None,
            }
            _CACHE_FILE.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            self.log.warning(f"Universe cache save failed: {e}")

    def _load_cache(self):
        try:
            if not _CACHE_FILE.exists():
                return
            data = json.loads(_CACHE_FILE.read_text())
            self.intraday = data.get("intraday", {})
            self.swing = data.get("swing", {})
            if data.get("intraday_at"):
                self._intraday_refreshed_at = datetime.fromisoformat(data["intraday_at"])
            if data.get("swing_at"):
                self._swing_refreshed_at = datetime.fromisoformat(data["swing_at"])
        except Exception as e:
            self.log.warning(f"Universe cache load failed: {e}")
