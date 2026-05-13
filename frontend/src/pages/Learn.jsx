import { useState } from "react";

const MODULES = [
  {
    id: "basics",
    icon: "◇",
    title: "Trading Basics",
    level: "Beginner",
    lessons: [
      {
        id: "what-is-trading",
        title: "What is Algorithmic Trading?",
        duration: "5 min",
        content: `Algorithmic trading (also called "algo trading") is the process of using computer programs to execute trades automatically based on predefined rules and conditions.

**Why use it?**
• Speed — computers execute in milliseconds, no emotion, no hesitation
• Consistency — the same rules applied identically every time
• Backtesting — test your strategy against historical data before risking real money
• 24/7 monitoring — no need to watch the screen constantly

**How AutoTrader works:**
Your bot connects to Alpaca's brokerage API, polls market data, evaluates your strategy's entry/exit conditions on each bar, and places orders automatically. You set the rules; the bot executes.`,
      },
      {
        id: "paper-vs-live",
        title: "Paper vs Live Trading",
        duration: "3 min",
        content: `**Paper Trading** uses simulated money with real market data. No real capital is at risk. This is how you:
• Test a new strategy without losing money
• Build confidence before going live
• Learn how the platform works

**Live Trading** uses real capital. Orders fill at real market prices. Profits and losses are real.

**Best practice:** Always paper trade a strategy for at least 2–4 weeks before going live. Verify the win rate and drawdown match your backtested expectations.`,
      },
      {
        id: "order-types",
        title: "Order Types Explained",
        duration: "4 min",
        content: `**Market Order** — buy/sell immediately at the current market price. Guaranteed fill, but price may vary slightly in fast markets.

**Limit Order** — buy/sell only at a specific price or better. You control the price, but there's no guarantee of fill if the price doesn't reach your level.

**Stop Order** — triggers a market order when a price threshold is hit. Used to limit losses (stop-loss) or lock in profits (trailing stop).

**Day Order** — expires at end of trading session if not filled.
**GTC (Good Till Cancelled)** — stays active until filled or manually cancelled.

AutoTrader uses market orders by default for fast execution. You can switch to limit orders from the Trade panel in the Stocks page.`,
      },
    ],
  },
  {
    id: "strategies",
    icon: "▦",
    title: "Strategy Deep Dives",
    level: "Intermediate",
    lessons: [
      {
        id: "ema-vwap",
        title: "EMA + VWAP Momentum Strategy",
        duration: "8 min",
        content: `**What it does:**
Buys when the fast EMA (9-period) crosses above the slow EMA (21-period) AND price is trading above the VWAP. Both conditions must be true to enter.

**Indicators explained:**

*EMA (Exponential Moving Average)* — a weighted average that gives more importance to recent prices. Faster to react than a simple moving average.

*VWAP (Volume Weighted Average Price)* — the average price weighted by volume throughout the day. Institutional traders use it as a benchmark. Price above VWAP = bullish bias; below = bearish.

**Entry logic:** EMA(9) crosses above EMA(21) + price > VWAP
**Exit logic:** EMA(9) crosses below EMA(21), or trailing stop triggered at 1.5× ATR

**Best for:** Trending, high-momentum stocks like NVDA, TSLA, AMD on 5-minute bars.
**Avoid during:** Low-volatility, range-bound sessions.`,
      },
      {
        id: "rsi-mean-rev",
        title: "RSI Mean Reversion Strategy",
        duration: "6 min",
        content: `**What it does:**
Buys when the stock is "oversold" (RSI below 30) and sells when it becomes "overbought" (RSI above 70). Works best on stable, range-bound stocks.

**The RSI (Relative Strength Index)** oscillates between 0 and 100:
• Below 30 = oversold (potentially a buying opportunity)
• Above 70 = overbought (potentially a selling opportunity)
• Around 50 = neutral

**Entry logic:** RSI(14) drops below 30 on hourly bars
**Exit logic:** RSI returns above 60, or 2% stop-loss from entry

**Best for:** Blue-chip stocks like AAPL, MSFT, JPM that tend to revert to their mean.
**Avoid during:** Strong trending markets — RSI can stay oversold for a long time in a downtrend.`,
      },
      {
        id: "orb",
        title: "Opening Range Breakout (ORB)",
        duration: "7 min",
        content: `**What it does:**
Records the high and low of the first 15 minutes after market open (9:30–9:45 AM ET). Then trades breakouts above or below that range.

**Why it works:**
The opening range often captures the initial price discovery battle. A clean breakout above the range with strong volume signals institutional buying. Below the range signals selling.

**Entry logic:** Price closes above ORB high (long) or below ORB low (short) with above-average volume
**Exit logic:** 1× ATR stop from entry, 2× ATR take-profit target

**Best for:** High-volatility stocks with a catalyst (earnings, news). SPY and QQQ on macro announcement days.
**Avoid during:** Low-volume pre-holiday sessions; choppy "inside day" markets.

**Risk note:** ORB is a higher-risk strategy. False breakouts (fakeouts) are common. Use smaller position sizes.`,
      },
    ],
  },
  {
    id: "risk",
    icon: "◉",
    title: "Risk Management",
    level: "Intermediate",
    lessons: [
      {
        id: "position-sizing",
        title: "Position Sizing & Kelly Criterion",
        duration: "6 min",
        content: `How much of your capital should you put in a single trade? This is position sizing — one of the most important decisions in trading.

**The 1% Rule:** Never risk more than 1% of your total portfolio on a single trade. If you have $10,000, your max loss per trade = $100.

**How to calculate position size:**
Position size = (Account risk $) / (Entry price - Stop loss price)

Example: $10,000 account, 1% risk = $100. Entry at $100, stop at $97.
Position size = $100 / ($100 - $97) = 33 shares.

**The Kelly Criterion** is a mathematical formula for optimal bet sizing:
Kelly % = Win rate - [(1 - Win rate) / Win:Loss ratio]

A strategy with 60% win rate and 2:1 reward:risk: 0.60 - (0.40 / 2) = 40% of capital.
In practice, use "half Kelly" (20% here) to reduce variance.`,
      },
      {
        id: "drawdown",
        title: "Understanding Drawdown",
        duration: "4 min",
        content: `**Drawdown** is the peak-to-trough decline in your portfolio value. It's the best measure of real risk.

A strategy that makes 50% returns but has a 40% maximum drawdown means at some point you would have been down 40% from your peak — very uncomfortable for most traders.

**Key metrics:**
• **Max Drawdown (MDD)** — worst peak-to-trough loss. A good strategy has MDD under 20%.
• **Calmar Ratio** — annualized return / max drawdown. Higher = better risk-adjusted returns.
• **Recovery time** — how long it took to recover from the worst drawdown.

**AutoTrader tip:** If your bot's drawdown exceeds 10% from its equity peak, consider pausing it and reviewing the strategy. Markets may have changed regime.`,
      },
    ],
  },
  {
    id: "alpaca",
    icon: "⚡",
    title: "Alpaca API Guide",
    level: "Advanced",
    lessons: [
      {
        id: "api-setup",
        title: "Setting Up Your Alpaca Account",
        duration: "5 min",
        content: `**Step 1: Create an account**
Go to app.alpaca.markets and sign up. Paper trading is free — no minimum balance.

**Step 2: Generate API keys**
In your Alpaca dashboard → API Keys → Generate New Key.
You'll get an API Key ID (starts with "PK...") and a Secret Key. Copy both — the secret is only shown once.

**Step 3: Paper vs Live**
Paper trading API base URL: https://paper-api.alpaca.markets
Live trading API base URL: https://api.alpaca.markets
Market data URL: https://data.alpaca.markets

**Step 4: Paste into AutoTrader**
Enter your keys during onboarding. Select "Paper Trading" to start safely.

**Security:** Your keys are stored locally in your browser and sent only to the Alpaca API. They are never stored on any AutoTrader server.`,
      },
      {
        id: "market-hours",
        title: "Market Hours & Trading Restrictions",
        duration: "4 min",
        content: `**US Stock Market Hours (Eastern Time):**
• Pre-market: 4:00 AM – 9:30 AM (limited liquidity)
• Regular hours: 9:30 AM – 4:00 PM (full liquidity)
• After-hours: 4:00 PM – 8:00 PM (limited liquidity)

**Alpaca supports** extended hours trading with limit orders only. Market orders execute only during regular hours.

**Pattern Day Trader (PDT) Rule:**
If your account is under $25,000, you're limited to 3 "day trades" (buy and sell same security same day) in a rolling 5-business-day period. Alpaca enforces this automatically.

**AutoTrader tip:** Paper trading accounts are NOT subject to PDT rules. This is another reason to start with paper trading and learn your strategy's behavior.`,
      },
    ],
  },
];

const LEVEL_COLOR = {
  Beginner:     { color: "var(--green)", bg: "rgba(74,222,128,0.1)" },
  Intermediate: { color: "var(--amber)", bg: "rgba(245,158,11,0.1)" },
  Advanced:     { color: "var(--blue)",  bg: "rgba(96,165,250,0.1)" },
};

function formatContent(text) {
  // Simple markdown-ish renderer
  return text.split("\n\n").map((para, i) => {
    if (para.startsWith("**") && para.endsWith("**") && !para.slice(2).includes("**")) {
      return <h4 key={i} style={{ fontSize: 14, fontWeight: 700, marginBottom: 6, marginTop: i > 0 ? 14 : 0 }}>{para.slice(2, -2)}</h4>;
    }
    const lines = para.split("\n").map((line, j) => {
      // Bold inline
      const parts = line.split(/(\*\*[^*]+\*\*)/g).map((p, k) =>
        p.startsWith("**") ? <strong key={k}>{p.slice(2, -2)}</strong> : p
      );
      if (line.startsWith("• ") || line.startsWith("* ")) {
        return <li key={j} style={{ marginLeft: 16, marginBottom: 4, color: "rgba(255,255,255,0.7)" }}>{parts.map(p => typeof p === "string" ? p.slice(2) : p)}</li>;
      }
      if (line.startsWith("*") && line.endsWith("*") && line.length > 2) {
        return <em key={j} style={{ color: "var(--blue)", fontStyle: "normal", fontWeight: 600 }}>{parts}</em>;
      }
      return <span key={j}>{parts}</span>;
    });
    const isList = para.includes("\n• ") || para.startsWith("• ");
    return isList
      ? <ul key={i} style={{ listStyle: "disc", paddingLeft: 4, marginBottom: 12 }}>{lines}</ul>
      : <p key={i} style={{ marginBottom: 10, color: "rgba(255,255,255,0.7)", lineHeight: 1.7 }}>{lines}</p>;
  });
}

export default function Learn() {
  const [activeModule,  setActiveModule]  = useState(null);
  const [activeLesson,  setActiveLesson]  = useState(null);
  const [completed,     setCompleted]     = useState(() => {
    try { return new Set(JSON.parse(sessionStorage.getItem("learn_done") || "[]")); }
    catch { return new Set(); }
  });

  const markDone = (id) => {
    setCompleted((prev) => {
      const next = new Set(prev);
      next.add(id);
      try { sessionStorage.setItem("learn_done", JSON.stringify([...next])); } catch {}
      return next;
    });
  };

  const currentModule = MODULES.find((m) => m.id === activeModule);
  const currentLesson = currentModule?.lessons.find((l) => l.id === activeLesson);

  const totalLessons    = MODULES.reduce((s, m) => s + m.lessons.length, 0);
  const completedCount  = MODULES.reduce((s, m) => s + m.lessons.filter((l) => completed.has(l.id)).length, 0);
  const progressPct     = Math.round((completedCount / totalLessons) * 100);

  return (
    <div className="page">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1>Learn</h1>
          <div className="page-header-meta">Trading education · {completedCount}/{totalLessons} lessons completed</div>
        </div>
        <div className="page-header-right">
          <div style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "8px 14px", background: "rgba(255,255,255,0.04)",
            border: "1px solid var(--border)", borderRadius: 8,
          }}>
            <div style={{ width: 80, height: 4, background: "rgba(255,255,255,0.1)", borderRadius: 2 }}>
              <div style={{ width: `${progressPct}%`, height: "100%", background: "var(--green)", borderRadius: 2, transition: "width 0.3s" }} />
            </div>
            <span style={{ fontSize: 13, color: "var(--green)", fontWeight: 600 }}>{progressPct}%</span>
          </div>
        </div>
      </div>

      {/* Lesson reader */}
      {currentLesson ? (
        <div>
          <button
            onClick={() => { setActiveLesson(null); }}
            style={{
              marginBottom: 20, background: "transparent", border: "none",
              color: "var(--blue)", fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
            }}
          >
            ← Back to {currentModule.title}
          </button>

          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
              <div>
                <div style={{ fontSize: 11, color: "var(--muted)", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {currentModule.title} · {currentLesson.duration}
                </div>
                <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em" }}>{currentLesson.title}</h2>
              </div>
              {!completed.has(currentLesson.id) && (
                <button
                  className="btn-primary"
                  onClick={() => markDone(currentLesson.id)}
                  style={{ flexShrink: 0 }}
                >
                  Mark Complete ✓
                </button>
              )}
              {completed.has(currentLesson.id) && (
                <span style={{ fontSize: 13, color: "var(--green)", fontWeight: 600 }}>✓ Completed</span>
              )}
            </div>

            <div style={{ maxWidth: 680, fontSize: 14, lineHeight: 1.7 }}>
              {formatContent(currentLesson.content)}
            </div>

            {/* Next lesson */}
            {(() => {
              const lessons = currentModule.lessons;
              const idx = lessons.findIndex((l) => l.id === activeLesson);
              const next = lessons[idx + 1];
              return next ? (
                <div
                  style={{
                    marginTop: 32, padding: "16px 20px", background: "rgba(96,165,250,0.06)",
                    border: "1px solid rgba(96,165,250,0.15)", borderRadius: 10,
                    display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer",
                  }}
                  onClick={() => { markDone(currentLesson.id); setActiveLesson(next.id); }}
                >
                  <div>
                    <div style={{ fontSize: 11, color: "var(--blue)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Next lesson</div>
                    <div style={{ fontSize: 15, fontWeight: 600 }}>{next.title}</div>
                  </div>
                  <span style={{ color: "var(--blue)", fontSize: 18 }}>→</span>
                </div>
              ) : null;
            })()}
          </div>
        </div>
      ) : activeModule ? (
        /* Module lesson list */
        <div>
          <button
            onClick={() => setActiveModule(null)}
            style={{
              marginBottom: 20, background: "transparent", border: "none",
              color: "var(--blue)", fontSize: 13, cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
            }}
          >
            ← All Modules
          </button>

          <div className="panel" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 4 }}>
              <span style={{ fontSize: 32 }}>{currentModule.icon}</span>
              <div>
                <h2 style={{ fontSize: 20, fontWeight: 700 }}>{currentModule.title}</h2>
                <span style={{
                  fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
                  background: LEVEL_COLOR[currentModule.level].bg,
                  color: LEVEL_COLOR[currentModule.level].color,
                }}>
                  {currentModule.level}
                </span>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {currentModule.lessons.map((lesson, i) => (
              <div
                key={lesson.id}
                className="panel"
                style={{
                  display: "flex", alignItems: "center", gap: 14,
                  cursor: "pointer", transition: "border-color 0.15s",
                }}
                onClick={() => setActiveLesson(lesson.id)}
              >
                <div style={{
                  width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: completed.has(lesson.id) ? "rgba(74,222,128,0.1)" : "rgba(255,255,255,0.04)",
                  border: `1px solid ${completed.has(lesson.id) ? "rgba(74,222,128,0.2)" : "var(--border)"}`,
                  color: completed.has(lesson.id) ? "var(--green)" : "var(--muted)",
                  fontSize: 13, fontWeight: 700,
                }}>
                  {completed.has(lesson.id) ? "✓" : i + 1}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{lesson.title}</div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{lesson.duration} read</div>
                </div>
                <span style={{ color: "var(--blue)", fontSize: 16 }}>→</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        /* Module grid */
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 14 }}>
          {MODULES.map((mod) => {
            const done = mod.lessons.filter((l) => completed.has(l.id)).length;
            const pct  = Math.round((done / mod.lessons.length) * 100);
            const lv   = LEVEL_COLOR[mod.level];
            return (
              <div
                key={mod.id}
                className="panel"
                style={{ cursor: "pointer", transition: "border-color 0.15s" }}
                onClick={() => setActiveModule(mod.id)}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
                  <span style={{ fontSize: 28, color: "var(--blue)" }}>{mod.icon}</span>
                  <span style={{
                    fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
                    background: lv.bg, color: lv.color,
                  }}>
                    {mod.level}
                  </span>
                </div>
                <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 6 }}>{mod.title}</div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 16 }}>
                  {mod.lessons.length} lessons
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ flex: 1, height: 3, background: "rgba(255,255,255,0.08)", borderRadius: 2 }}>
                    <div style={{ width: `${pct}%`, height: "100%", background: lv.color, borderRadius: 2, transition: "width 0.3s" }} />
                  </div>
                  <span style={{ fontSize: 11, color: lv.color, fontWeight: 600, whiteSpace: "nowrap" }}>{done}/{mod.lessons.length}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
