import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../api/alpaca";

const RISK_LABEL = { Low: "low", Medium: "medium", High: "high", Variable: "medium" };

export default function Strategy() {
  const { auth } = useAuth();
  const [strategies,  setStrategies]  = useState([]);
  const [selected,    setSelected]    = useState(null);
  const [botStatus,   setBotStatus]   = useState({ running: false, logs: [], strategies: {} });
  const [customText,  setCustomText]  = useState("");
  const [loading,     setLoading]     = useState(false);
  const [tab,         setTab]         = useState("browse");

  useEffect(() => {
    api.strategies().then(setStrategies).catch(console.error);
    pollStatus();
    const iv = setInterval(pollStatus, 3000);
    return () => clearInterval(iv);
  }, []);

  async function pollStatus() {
    try { setBotStatus(await api.botStatus()); } catch {}
  }

  async function startBot() {
    if (!selected) return;
    setLoading(true);
    try {
      await api.botStart({
        api_key:    auth.apiKey,
        secret_key: auth.secretKey,
        paper:      auth.paper,
        strategy:   selected.id,
      });
      await pollStatus();
    } catch (e) { alert("Failed to start: " + e.message); }
    finally { setLoading(false); }
  }

  async function stopBot() {
    if (!selected) return;
    setLoading(true);
    try { await api.botStop(selected.id); await pollStatus(); }
    catch (e) { alert("Failed to stop: " + e.message); }
    finally { setLoading(false); }
  }

  // Is the currently selected strategy running?
  const selectedRunning = selected
    ? !!(botStatus.strategies?.[selected.id]?.running)
    : false;

  const TAB_STYLE = (active) => ({
    padding: "8px 18px",
    border: "none",
    background: active ? "rgba(96,165,250,0.12)" : "transparent",
    color: active ? "var(--blue)" : "var(--muted)",
    borderRadius: "var(--radius-sm)",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
    transition: "all 0.15s",
  });

  return (
    <div className="page">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="page-header">
        <div>
          <h1>Strategies</h1>
          <div className="page-header-meta">Browse presets or describe your own</div>
        </div>
        <div className="page-header-right">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              background: botStatus.running ? "rgba(74,222,128,0.1)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${botStatus.running ? "rgba(74,222,128,0.2)" : "var(--border)"}`,
              borderRadius: "var(--radius-sm)",
              fontSize: 13,
              fontWeight: 600,
              color: botStatus.running ? "var(--green)" : "var(--muted)",
            }}
          >
            <span
              className={botStatus.running ? "pulse-dot green" : "pulse-dot green"}
              style={{ opacity: botStatus.running ? 1 : 0.3 }}
            />
            {Object.values(botStatus.strategies || {}).filter(s => s.running).length > 0
              ? `${Object.values(botStatus.strategies || {}).filter(s => s.running).length} Bot(s) Running`
              : "All Bots Stopped"}
          </div>
        </div>
      </div>

      {/* ── Tabs ───────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 4, marginBottom: 20 }}>
        {["browse", "custom", "logs"].map((t) => (
          <button key={t} style={TAB_STYLE(tab === t)} onClick={() => setTab(t)}>
            {t === "browse" ? "Browse Strategies" : t === "custom" ? "Custom Strategy" : "Bot Logs"}
            {t === "logs" && botStatus.running && (              <span style={{ marginLeft: 6, width: 6, height: 6, background: "var(--green)", borderRadius: 3, display: "inline-block" }} />
            )}
          </button>
        ))}
      </div>

      {/* ── Browse ─────────────────────────────────────────────────────── */}
      {tab === "browse" && (
        <div>
          <div className="strategy-grid">
            {(strategies.length > 0 ? strategies.filter((s) => s.id !== "custom") : FALLBACK_STRATEGIES).map((s) => (
              <button
                key={s.id}
                className={`strategy-card ${selected?.id === s.id ? "active" : ""}`}
                onClick={() => setSelected(s)}
                style={{ display: "block" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                  <div className="strategy-card-name">{s.name}</div>
                  <span className={`risk-badge ${RISK_LABEL[s.risk] || "medium"}`}>
                    {s.risk} Risk
                  </span>
                </div>
                <p className="strategy-card-desc">{s.description || s.desc}</p>
                <div className="strategy-card-stats">
                  {s.timeframe && <span>Timeframe: <b style={{ color: "var(--blue)" }}>{s.timeframe}</b></span>}
                  {s.winRate   && <span>Win Rate: <b style={{ color: "var(--green)" }}>{s.winRate}</b></span>}
                </div>
              </button>
            ))}
          </div>

          {/* Control bar */}
          {selected && (
            <div
              className="panel"
              style={{ marginTop: 16, display: "flex", alignItems: "center", justifyContent: "space-between" }}
            >
              <div>
                <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 4 }}>Selected strategy</div>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{selected.name}</div>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div className="mode-badge">
                  <div className={`mode-dot${auth?.paper === false ? " live" : ""}`} />
                  {auth?.paper === false ? "Live" : "Paper"}
                </div>
                {!selectedRunning ? (
                  <button
                    className="bot-ctrl-btn stopped"
                    onClick={startBot}
                    disabled={loading}
                  >
                    {loading ? <span className="btn-spinner" /> : <><span className="pulse-dot green" />Start Bot</>}
                  </button>
                ) : (
                  <button
                    className="bot-ctrl-btn running"
                    onClick={stopBot}
                    disabled={loading}
                  >
                    {loading ? <span className="btn-spinner" /> : <><span className="pulse-dot red" />Stop Bot</>}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Custom ─────────────────────────────────────────────────────── */}
      {tab === "custom" && (
        <div className="panel">
          <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>Describe Your Strategy</h3>
          <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 20, lineHeight: 1.6 }}>
            Explain your trading logic in plain English. The system will map it to configurable
            parameters and launch the closest matching engine.
          </p>
          <textarea
            style={{
              width: "100%",
              minHeight: 160,
              padding: "14px 16px",
              background: "rgba(255,255,255,0.03)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text)",
              fontSize: 14,
              fontFamily: "var(--sans)",
              lineHeight: 1.6,
              outline: "none",
              resize: "vertical",
            }}
            placeholder="Example: Buy when RSI drops below 35 and the stock is above its 200-day moving average. Exit when RSI reaches 60 or price drops 2% from entry…"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
          />
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16 }}>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>{customText.length} chars</span>
            <button
              className="btn-primary"
              disabled={customText.length < 20}
              onClick={() => {
                const allStrats = strategies.length > 0 ? strategies : FALLBACK_STRATEGIES;
                const custom = allStrats.find((s) => s.id === "custom") || {
                  id: "custom", name: "Custom Strategy", risk: "Variable", timeframe: "Any",
                };
                setSelected({ ...custom, customText });
                setTab("browse");
              }}
            >
              Apply Custom Strategy
            </button>
          </div>
          <div style={{ marginTop: 24 }}>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>Quick examples</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {[
                "Buy NVDA on RSI dip below 30, sell at 3% gain or 1.5% loss",
                "Trade ORB breakouts on AAPL and TSLA in the first 30 minutes",
                "EMA crossover strategy on MSFT, 9/21 EMA, 5-min bars",
              ].map((ex) => (
                <button
                  key={ex}
                  onClick={() => setCustomText(ex)}
                  style={{
                    padding: "10px 14px",
                    background: "rgba(255,255,255,0.02)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-sm)",
                    color: "var(--muted)",
                    fontSize: 13,
                    textAlign: "left",
                    cursor: "pointer",
                    transition: "all 0.15s",
                  }}
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Logs ───────────────────────────────────────────────────────── */}
      {tab === "logs" && (
        <div className="panel">
          {/* Per-strategy log sections */}
          {Object.entries(botStatus.strategies || {}).length === 0 ? (
            <div className="empty-state">No bots started yet</div>
          ) : (
            Object.entries(botStatus.strategies || {}).map(([sid, info]) => {
              const label = sid.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
              return (
                <div key={sid} style={{ marginBottom: 20 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <span className="panel-title">{label}</span>
                    {info.running && (
                      <span style={{ fontSize: 12, fontWeight: 700, color: "var(--green)", display: "flex", alignItems: "center", gap: 6 }}>
                        <span className="pulse-dot green" /> LIVE
                      </span>
                    )}
                  </div>
                  {(info.logs || []).length === 0 ? (
                    <div className="empty-state" style={{ fontSize: 12 }}>No logs yet</div>
                  ) : (
                    <div className="log-panel">
                      {(info.logs || []).map((line, i) => (
                        <div
                          key={i}
                          style={{
                            color: line.includes("ERROR") ? "var(--red)"
                                 : line.includes("WARN")  ? "var(--amber)"
                                 : line.includes("BUY") || line.includes("SELL") ? "var(--green)"
                                 : undefined,
                          }}
                        >
                          {line}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}

const FALLBACK_STRATEGIES = [
  { id: "ema_vwap", name: "Momentum Rider",  description: "EMA/VWAP crossover — follows strong price trends with dynamic trailing stops",       risk: "Medium", timeframe: "5 min",  winRate: "64%" },
  { id: "rsi",      name: "Mean Reversion",  description: "RSI-based dip buying on range-bound stocks. Enters on oversold, exits on recovery", risk: "Low",    timeframe: "15 min", winRate: "71%" },
  { id: "orb",      name: "Breakout Hunter", description: "Opening range breakout — detects and trades volume-backed first-hour breakouts",     risk: "High",   timeframe: "1 min",  winRate: "52%" },
];
