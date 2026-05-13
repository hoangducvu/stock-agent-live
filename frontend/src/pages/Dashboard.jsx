import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../api/alpaca";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";

/* ── helpers ─────────────────────────────────────────────────────────────── */
const fmtMoney = (n) =>
  `$${parseFloat(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtPct = (n) =>
  `${parseFloat(n || 0) >= 0 ? "+" : ""}${parseFloat(n || 0).toFixed(2)}%`;

const STRATEGY_ID_MAP = { "ema_vwap": "ema_vwap", "orb": "orb", "rsi": "rsi" };

/* ── sub-components ──────────────────────────────────────────────────────── */
function StatCard({ label, value, sub, color }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${color || ""}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

function CustomTooltip({ active, payload }) {
  if (active && payload?.length) {
    return (
      <div className="chart-tooltip">
        <div className="ct-label">{payload[0]?.payload?.time}</div>
        <div className="ct-value">{fmtMoney(payload[0].value)}</div>
      </div>
    );
  }
  return null;
}

function BotToggle({ active, onToggle }) {
  return (
    <button
      className={`bot-toggle ${active ? "on" : "off"}`}
      onClick={onToggle}
      title={active ? "Pause bot" : "Activate bot"}
    >
      <div className="bot-toggle-dot" />
    </button>
  );
}

/* ── main Dashboard ──────────────────────────────────────────────────────── */
export default function Dashboard() {
  const { headers, auth } = useAuth();
  const navigate = useNavigate();

  const [account,    setAccount]    = useState(null);
  const [positions,  setPositions]  = useState([]);
  const [history,    setHistory]    = useState([]);
  const [orders,     setOrders]     = useState([]);
  const [period,     setPeriod]     = useState("1W");
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState("");

  /* bot state */
  const [botRunning,   setBotRunning]   = useState(false);
  const [botToggling,  setBotToggling]  = useState(false);
  const [botLogs,      setBotLogs]      = useState([]);
  const [bots,         setBots]         = useState([]);
  const [botsLoading,  setBotsLoading]  = useState(true);
  const [togglingBot,  setTogglingBot]  = useState(null);  // strategy_id being toggled
  /* test order state */
  const [testSymbol,   setTestSymbol]   = useState("AAPL");
  const [testQty,      setTestQty]      = useState(1);
  const [testSide,     setTestSide]     = useState("buy");
  const [testResult,   setTestResult]   = useState(null);
  const [testRunning,  setTestRunning]  = useState(false);
  const logEndRef = useRef(null);

  /* ── data loading ──────────────────────────────────────────────────────── */
  const load = useCallback(async () => {
    try {
      const [acct, pos, ord] = await Promise.all([
        api.account(headers),
        api.positions(headers),
        api.orders(headers, "all", 10),
      ]);
      setAccount(acct);
      setPositions(pos);
      setOrders(ord);

      try {
        const hist = await api.portfolioHistory(
          headers,
          period,
          period === "1D" ? "5Min" : "1D"
        );
        if (hist.timestamp && hist.equity) {
          setHistory(
            hist.timestamp.map((ts, i) => ({
              time: new Date(ts * 1000).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              }),
              value: hist.equity[i] || 0,
            }))
          );
        }
      } catch {}
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [headers, period]);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  /* ── bot polling ───────────────────────────────────────────────────────── */
  const pollBot = useCallback(async () => {
    try {
      const s = await api.botStatus();
      setBotRunning(s.running);
      if (s.logs?.length) {
        setBotLogs(s.logs);
        setTimeout(() => logEndRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
      }
    } catch {}
  }, []);

  const loadBots = useCallback(async () => {
    try {
      const data = await api.bots();
      setBots(data);
    } catch {}
    finally { setBotsLoading(false); }
  }, []);

  useEffect(() => {
    pollBot();
    const iv = setInterval(pollBot, 3000);
    return () => clearInterval(iv);
  }, [pollBot]);

  useEffect(() => {
    loadBots();
    const iv = setInterval(loadBots, 5000);
    return () => clearInterval(iv);
  }, [loadBots]);

  const toggleMainBot = async () => {
    setBotToggling(true);
    try {
      if (botRunning) {
        await api.botStop();
        setBotRunning(false);
      } else {
        await api.botStart({
          api_key:   auth?.apiKey    || "",
          secret_key:auth?.secretKey || "",
          paper:     auth?.paper     ?? true,
          strategy:  auth?.strategy  || "ema_vwap",
        });
        setBotRunning(true);
      }
    } catch (e) {
      alert("Bot error: " + e.message);
    } finally {
      setBotToggling(false);
    }
  };

  const toggleStrategyBot = async (bot) => {
    setTogglingBot(bot.strategy_id);
    try {
      if (bot.status === "active") {
        await api.botStop(bot.strategy_id);
      } else {
        await api.botStart({
          api_key:    auth?.apiKey    || "",
          secret_key: auth?.secretKey || "",
          paper:      auth?.paper     ?? true,
          strategy:   bot.strategy_id,
        });
      }
      // Brief wait so backend state settles before re-polling
      await new Promise((r) => setTimeout(r, 600));
      await Promise.all([loadBots(), pollBot()]);
    } catch (e) {
      alert("Bot error: " + e.message);
    } finally {
      setTogglingBot(null);
    }
  };

  const runTestOrder = async () => {
    setTestRunning(true);
    setTestResult(null);
    try {
      const result = await api.testOrder(headers, testSymbol, testQty, testSide);
      setTestResult({ ok: true, data: result });
    } catch (e) {
      setTestResult({ ok: false, error: e.message });
    } finally {
      setTestRunning(false);
    }
  };

  /* ── derived values ────────────────────────────────────────────────────── */
  const equity     = parseFloat(account?.equity        || 0);
  const lastEquity = parseFloat(account?.last_equity   || equity);
  const pnl        = equity - lastEquity;
  const pnlPct     = lastEquity > 0 ? (pnl / lastEquity) * 100 : 0;
  const activeBots = bots.filter((b) => b.status === "active").length;
  const totalBots  = bots.length || 3;

  /* ── render ────────────────────────────────────────────────────────────── */
  if (loading) return <div className="page-loading"><div className="spinner" /><span>Loading…</span></div>;
  if (error)   return <div className="page-error">⚠ {error} — is the backend running?</div>;

  return (
    <div className="page">
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <div className="page-header-meta">Welcome back — here's your performance overview</div>
        </div>
        <div className="page-header-right">
          <div className="mode-badge">
            <div className={`mode-dot${auth?.paper === false ? " live" : ""}`} />
            {auth?.paper === false ? "Live Trading" : "Paper Trading"}
          </div>
          <button
            className={`bot-ctrl-btn ${botRunning ? "running" : "stopped"}`}
            onClick={toggleMainBot}
            disabled={botToggling}
          >
            {botToggling ? (
              <span className="btn-spinner" />
            ) : botRunning ? (
              <><span className="pulse-dot red" />Stop Bot</>
            ) : (
              <><span className="pulse-dot green" />Start Trading</>
            )}
          </button>
        </div>
      </div>

      {/* ── Stats row ────────────────────────────────────────────────────── */}
      <div className="stats-row">
        <StatCard
          label="Portfolio Value"
          value={fmtMoney(equity)}
          sub="Updated just now"
        />
        <StatCard
          label="Total P&L"
          value={`${pnl >= 0 ? "+" : ""}${fmtMoney(pnl)}`}
          sub={fmtPct(pnlPct)}
          color={pnl >= 0 ? "green" : "red"}
        />
        <StatCard
          label="Active Bots"
          value={`${activeBots} / ${totalBots}`}
          sub={`${activeBots} strategies running`}
        />
        <StatCard
          label="Open Positions"
          value={positions.length}
          sub={positions.length > 0 ? "Click Stocks to view" : "No open positions"}
          color="blue"
        />
      </div>

      {/* ── Chart + Recent Trades ─────────────────────────────────────────── */}
      <div className="chart-trades-row">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Equity Curve</span>
            <div className="period-tabs">
              {["1D", "1W", "1M", "3M"].map((p) => (
                <button
                  key={p}
                  className={`period-tab ${period === p ? "active" : ""}`}
                  onClick={() => setPeriod(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div className="chart-wrap">
            {history.length > 1 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor={pnl >= 0 ? "#4ade80" : "#f87171"} stopOpacity={0.25} />
                      <stop offset="95%" stopColor={pnl >= 0 ? "#4ade80" : "#f87171"} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="time" tick={{ fill: "rgba(255,255,255,0.25)", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis
                    tick={{ fill: "rgba(255,255,255,0.25)", fontSize: 11 }}
                    width={68}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="value"
                    stroke={pnl >= 0 ? "#4ade80" : "#f87171"}
                    fill="url(#eqGrad)"
                    strokeWidth={2}
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="empty-chart">No history data yet</div>
            )}
          </div>
        </div>

        {/* Recent Trades */}
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Recent Trades</span>
          </div>
          {orders.length === 0 ? (
            <div className="empty-state">No recent orders — place a test trade below</div>
          ) : orders.map((t, i) => {
            const side = (t.side || "buy").toUpperCase();
            const sym  = t.symbol;
            const time = t.submitted_at
              ? new Date(t.submitted_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false })
              : "—";
            return (
              <div className="trade-row" key={i}>
                <span style={{ fontSize: 11, color: "rgba(255,255,255,0.25)", fontFamily: "var(--mono)", width: 42 }}>
                  {time}
                </span>
                <span style={{ fontWeight: 700, fontSize: 13, width: 52, fontFamily: "var(--mono)" }}>{sym}</span>
                <span style={{ fontSize: 12, color: side === "BUY" ? "var(--green)" : "var(--red)", width: 36 }}>
                  {side}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: 12, flex: 1, textAlign: "right", color: "rgba(255,255,255,0.35)" }}>
                  {t.filled_avg_price ? `$${parseFloat(t.filled_avg_price).toFixed(2)}` : t.status || "—"}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Bots Table ───────────────────────────────────────────────────── */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <span className="panel-title">Your Bots</span>
          <button className="btn-sm" onClick={() => navigate("/strategy")}>Configure</button>
        </div>

        {/* Table header */}
        <div className="bots-table-header">
          <span style={{ flex: 1 }}>Strategy</span>
          <span style={{ minWidth: 120 }}>Stocks</span>
          <span style={{ width: 70, textAlign: "right" }}>Trades</span>
          <span style={{ width: 60, textAlign: "right" }}>Win %</span>
          <span style={{ width: 100, textAlign: "right" }}>P&L Today</span>
          <span style={{ width: 44 }}></span>
        </div>

        {botsLoading ? (
          <div className="empty-state"><span className="btn-spinner" style={{ display: "inline-block" }} /> Loading bots…</div>
        ) : bots.length === 0 ? (
          <div className="empty-state">No bots found — start the backend to load strategies</div>
        ) : bots.map((bot) => {
          const isActive    = bot.status === "active";
          const isToggling  = togglingBot === bot.strategy_id;
          const statusColor = isActive ? "var(--green)" : "rgba(255,255,255,0.18)";
          return (
            <div className="bot-row" key={bot.id}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
                <div className="bot-status-dot" style={{ background: statusColor }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {bot.name}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--muted)" }}>
                    {isActive ? "● Running" : "○ Stopped"}
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 4, minWidth: 120, flexWrap: "wrap" }}>
                {bot.stocks.slice(0, 3).map((s) => (
                  <span key={s} className="stock-tag">{s}</span>
                ))}
              </div>
              <div style={{ width: 70, textAlign: "right", fontFamily: "var(--mono)", fontSize: 13 }}>
                {bot.trades}
              </div>
              <div style={{ width: 60, textAlign: "right", fontFamily: "var(--mono)", fontSize: 13, color: "var(--blue)" }}>
                {bot.winRate > 0 ? `${bot.winRate}%` : "—"}
              </div>
              <div style={{ width: 100, textAlign: "right", fontFamily: "var(--mono)", fontSize: 13, fontWeight: 600, color: bot.pnl >= 0 ? "var(--green)" : "var(--red)" }}>
                {bot.pnl !== 0 ? `${bot.pnl >= 0 ? "+" : ""}$${Math.abs(bot.pnl).toFixed(2)}` : "—"}
              </div>
              <div style={{ width: 44, display: "flex", justifyContent: "flex-end" }}>
                {isToggling ? (
                  <span className="btn-spinner" style={{ display: "inline-block", width: 18, height: 18 }} />
                ) : (
                  <BotToggle
                    active={isActive}
                    onToggle={() => toggleStrategyBot(bot)}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Test Trade Panel ─────────────────────────────────────────────── */}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-header">
          <span className="panel-title">Test Order</span>
          <span style={{ fontSize: 12, color: "var(--muted)" }}>
            {auth?.paper === false ? "⚠ LIVE mode" : "Paper trading — safe to test"}
          </span>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {/* Side */}
          <div style={{ display: "flex", borderRadius: "var(--radius-sm)", overflow: "hidden", border: "1px solid var(--border)" }}>
            {["buy", "sell"].map((s) => (
              <button
                key={s}
                onClick={() => setTestSide(s)}
                style={{
                  padding: "7px 16px", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600,
                  background: testSide === s ? (s === "buy" ? "rgba(74,222,128,0.18)" : "rgba(248,113,113,0.18)") : "transparent",
                  color: testSide === s ? (s === "buy" ? "var(--green)" : "var(--red)") : "var(--muted)",
                  transition: "all 0.15s",
                }}
              >
                {s.toUpperCase()}
              </button>
            ))}
          </div>
          {/* Symbol */}
          <input
            value={testSymbol}
            onChange={(e) => setTestSymbol(e.target.value.toUpperCase())}
            style={{
              width: 90, padding: "7px 12px", background: "rgba(255,255,255,0.04)",
              border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
              color: "var(--text)", fontSize: 13, fontFamily: "var(--mono)", outline: "none",
            }}
            placeholder="AAPL"
          />
          {/* Qty */}
          <input
            type="number"
            min="1"
            value={testQty}
            onChange={(e) => setTestQty(Math.max(1, parseInt(e.target.value) || 1))}
            style={{
              width: 70, padding: "7px 12px", background: "rgba(255,255,255,0.04)",
              border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
              color: "var(--text)", fontSize: 13, fontFamily: "var(--mono)", outline: "none",
            }}
            placeholder="Qty"
          />
          <span style={{ fontSize: 12, color: "var(--muted)" }}>shares</span>
          <button
            className={`bot-ctrl-btn ${testSide === "buy" ? "stopped" : "running"}`}
            onClick={runTestOrder}
            disabled={testRunning || !testSymbol}
            style={{ marginLeft: "auto" }}
          >
            {testRunning ? <span className="btn-spinner" /> : `Execute ${testSide.toUpperCase()} ${testQty} ${testSymbol}`}
          </button>
        </div>

        {/* Result */}
        {testResult && (
          <div style={{
            marginTop: 12, padding: "12px 16px",
            background: testResult.ok ? "rgba(74,222,128,0.06)" : "rgba(248,113,113,0.06)",
            border: `1px solid ${testResult.ok ? "rgba(74,222,128,0.2)" : "rgba(248,113,113,0.2)"}`,
            borderRadius: "var(--radius-sm)", fontSize: 13, fontFamily: "var(--mono)",
          }}>
            {testResult.ok ? (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
                <span style={{ color: "var(--green)", fontWeight: 700 }}>✓ Order Submitted</span>
                <span>ID: <b>{testResult.data.order_id?.slice(0, 8)}…</b></span>
                <span>{testResult.data.side?.toUpperCase()} {testResult.data.qty} {testResult.data.symbol}</span>
                <span style={{ color: "var(--muted)" }}>status: {testResult.data.status}</span>
                <span style={{ color: "var(--muted)" }}>{testResult.data.paper ? "paper" : "live"}</span>
              </div>
            ) : (
              <span style={{ color: "var(--red)" }}>✗ {testResult.error}</span>
            )}
          </div>
        )}
      </div>

      {/* ── Open Positions + Bot Log ──────────────────────────────────────── */}
      <div className="two-col">
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Open Positions</span>
          </div>
          {positions.length === 0 ? (
            <div className="empty-state">No open positions</div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Entry</th>
                  <th>Current</th>
                  <th>P&L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const pl = parseFloat(p.unrealized_pl);
                  return (
                    <tr key={p.symbol}>
                      <td><strong style={{ fontFamily: "var(--mono)" }}>{p.symbol}</strong></td>
                      <td style={{ fontFamily: "var(--mono)" }}>{p.qty}</td>
                      <td style={{ fontFamily: "var(--mono)" }}>{fmtMoney(p.avg_entry_price)}</td>
                      <td style={{ fontFamily: "var(--mono)" }}>{fmtMoney(p.current_price)}</td>
                      <td className={pl >= 0 ? "green" : "red"}>
                        {fmtMoney(pl)}
                        <span className="pct">({(parseFloat(p.unrealized_plpc || 0) * 100).toFixed(2)}%)</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Bot Activity Log</span>
            <div
              className="pulse-dot green"
              style={{ opacity: botRunning ? 1 : 0.3 }}
              title={botRunning ? "Running" : "Stopped"}
            />
          </div>
          {botLogs.length === 0 ? (
            <div className="empty-state">No log entries yet — start the bot to begin</div>
          ) : (
            <div className="log-panel">
              {botLogs.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
              <div ref={logEndRef} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
