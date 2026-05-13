import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../api/alpaca";

const UNIVERSE = [
  { sym: "AAPL",  name: "Apple Inc."             },
  { sym: "MSFT",  name: "Microsoft Corp."         },
  { sym: "NVDA",  name: "NVIDIA Corp."            },
  { sym: "GOOGL", name: "Alphabet Inc."           },
  { sym: "AMZN",  name: "Amazon.com"              },
  { sym: "META",  name: "Meta Platforms"          },
  { sym: "TSLA",  name: "Tesla Inc."              },
  { sym: "AMD",   name: "Advanced Micro Devices"  },
  { sym: "SPY",   name: "S&P 500 ETF"             },
  { sym: "QQQ",   name: "Nasdaq 100 ETF"          },
  { sym: "PLTR",  name: "Palantir Technologies"   },
  { sym: "JPM",   name: "JPMorgan Chase"          },
  { sym: "V",     name: "Visa Inc."               },
  { sym: "BAC",   name: "Bank of America"         },
];

const fmtMoney = (n) =>
  n ? `$${parseFloat(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "—";
const fmtPct = (n) =>
  n !== undefined ? `${parseFloat(n) >= 0 ? "+" : ""}${parseFloat(n).toFixed(2)}%` : "—";

/* ── Order Modal ─────────────────────────────────────────────────────────── */
function OrderModal({ stock, onClose, onFilled, headers }) {
  const [side,       setSide]       = useState("buy");
  const [qty,        setQty]        = useState("1");
  const [orderType,  setOrderType]  = useState("market");
  const [limitPrice, setLimitPrice] = useState(stock.price ? stock.price.toFixed(2) : "");
  const [submitting, setSubmitting] = useState(false);
  const [error,      setError]      = useState("");
  const [success,    setSuccess]    = useState("");

  const estimated = parseFloat(qty || 0) * (stock.price || 0);

  const submit = async () => {
    setError(""); setSuccess("");
    const q = parseFloat(qty);
    if (!q || q <= 0) { setError("Enter a valid quantity."); return; }
    if (orderType === "limit" && (!limitPrice || parseFloat(limitPrice) <= 0)) {
      setError("Enter a valid limit price."); return;
    }
    setSubmitting(true);
    try {
      await api.placeOrder(headers, {
        symbol: stock.sym,
        qty: q,
        side,
        type: orderType,
        time_in_force: "day",
        ...(orderType === "limit" ? { limit_price: parseFloat(limitPrice) } : {}),
      });
      setSuccess(`${side.toUpperCase()} order for ${q} × ${stock.sym} placed successfully!`);
      setTimeout(() => { onFilled(); onClose(); }, 1500);
    } catch (e) {
      setError(e.message || "Order failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: "#0d1220", border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 16, padding: "28px 32px", width: 400, maxWidth: "92vw",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--mono)" }}>{stock.sym}</div>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>{stock.name}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--mono)" }}>
              {fmtMoney(stock.price || undefined)}
            </div>
            <div style={{ fontSize: 12, color: stock.chg >= 0 ? "var(--green)" : "var(--red)", fontFamily: "var(--mono)" }}>
              {stock.price ? `${stock.chg >= 0 ? "+" : ""}${stock.chg.toFixed(2)} (${fmtPct(stock.chgPct)})` : "—"}
            </div>
          </div>
        </div>

        {/* Side toggle */}
        <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
          {["buy", "sell"].map((s) => (
            <button
              key={s}
              onClick={() => setSide(s)}
              style={{
                flex: 1, padding: "10px 0", border: "1px solid",
                borderColor: side === s ? (s === "buy" ? "var(--green)" : "var(--red)") : "var(--border)",
                borderRadius: 8, background: side === s
                  ? (s === "buy" ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)")
                  : "transparent",
                color: side === s ? (s === "buy" ? "var(--green)" : "var(--red)") : "var(--muted)",
                fontWeight: 700, fontSize: 14, cursor: "pointer", transition: "all 0.15s",
              }}
            >
              {s.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Order type */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 6 }}>Order Type</label>
          <div style={{ display: "flex", gap: 8 }}>
            {["market", "limit"].map((t) => (
              <button
                key={t}
                onClick={() => setOrderType(t)}
                style={{
                  padding: "7px 16px", border: "1px solid",
                  borderColor: orderType === t ? "var(--blue)" : "var(--border)",
                  borderRadius: 6, background: orderType === t ? "rgba(96,165,250,0.1)" : "transparent",
                  color: orderType === t ? "var(--blue)" : "var(--muted)",
                  fontSize: 13, fontWeight: 600, cursor: "pointer", transition: "all 0.15s",
                }}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Quantity */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 6 }}>Quantity (shares)</label>
          <input
            type="number"
            min="1"
            step="1"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            style={{
              width: "100%", padding: "10px 14px",
              background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 8, color: "#fff", fontSize: 14, fontFamily: "var(--mono)", outline: "none",
            }}
          />
        </div>

        {/* Limit price */}
        {orderType === "limit" && (
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 12, color: "var(--muted)", display: "block", marginBottom: 6 }}>Limit Price ($)</label>
            <input
              type="number"
              min="0.01"
              step="0.01"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              style={{
                width: "100%", padding: "10px 14px",
                background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 8, color: "#fff", fontSize: 14, fontFamily: "var(--mono)", outline: "none",
              }}
            />
          </div>
        )}

        {/* Estimated value */}
        {estimated > 0 && (
          <div style={{
            padding: "10px 14px", background: "rgba(255,255,255,0.03)",
            border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16,
            fontSize: 13, color: "var(--muted)", display: "flex", justifyContent: "space-between",
          }}>
            <span>Estimated {side === "buy" ? "cost" : "proceeds"}</span>
            <span style={{ fontFamily: "var(--mono)", fontWeight: 600, color: "var(--text)" }}>
              {fmtMoney(estimated)}
            </span>
          </div>
        )}

        {error   && <div style={{ padding: "8px 12px", background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.2)", borderRadius: 7, color: "var(--red)", fontSize: 13, marginBottom: 12 }}>{error}</div>}
        {success && <div style={{ padding: "8px 12px", background: "rgba(74,222,128,0.1)",  border: "1px solid rgba(74,222,128,0.2)",  borderRadius: 7, color: "var(--green)", fontSize: 13, marginBottom: 12 }}>{success}</div>}

        {/* Actions */}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              flex: 1, padding: "11px 0", background: "transparent",
              border: "1px solid var(--border)", borderRadius: 8,
              color: "var(--muted)", fontSize: 14, fontWeight: 600, cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            style={{
              flex: 2, padding: "11px 0", border: "none", borderRadius: 8,
              background: side === "buy" ? "var(--green)" : "var(--red)",
              color: "#000", fontSize: 14, fontWeight: 700, cursor: submitting ? "not-allowed" : "pointer",
              opacity: submitting ? 0.6 : 1, transition: "opacity 0.15s",
            }}
          >
            {submitting ? "Placing…" : `Place ${side.toUpperCase()} Order`}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────────────────────────── */
export default function Stocks() {
  const { headers } = useAuth();
  const [quotes,    setQuotes]    = useState({});
  const [positions, setPositions] = useState({});
  const [loading,   setLoading]   = useState(true);
  const [search,    setSearch]    = useState("");
  const [sortBy,    setSortBy]    = useState("sym");
  const [sortAsc,   setSortAsc]   = useState(true);
  const [orderStock, setOrderStock] = useState(null); // stock row for modal

  const load = async () => {
    try {
      const [q, pos] = await Promise.all([
        api.quotes(UNIVERSE.map((u) => u.sym).join(","), headers),
        api.positions(headers),
      ]);
      setQuotes(q || {});
      const posMap = {};
      (pos || []).forEach((p) => (posMap[p.symbol] = p));
      setPositions(posMap);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [headers]);

  const rows = UNIVERSE.map((u) => {
    const snap  = quotes[u.sym];
    const price = snap?.latestTrade?.p || snap?.minuteBar?.c || 0;
    const prev  = snap?.prevDailyBar?.c || price;
    const chg   = price - prev;
    const chgPct= prev > 0 ? (chg / prev) * 100 : 0;
    const vol   = snap?.dailyBar?.v || 0;
    const pos   = positions[u.sym];
    return { ...u, price, chg, chgPct, vol, pos };
  });

  const filtered = rows.filter(
    (r) =>
      r.sym.toLowerCase().includes(search.toLowerCase()) ||
      r.name.toLowerCase().includes(search.toLowerCase())
  );

  const sorted = [...filtered].sort((a, b) => {
    let va = a[sortBy], vb = b[sortBy];
    if (typeof va === "string") { va = va.toLowerCase(); vb = vb.toLowerCase(); }
    return sortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
  });

  const handleSort = (col) => {
    if (sortBy === col) setSortAsc(!sortAsc);
    else { setSortBy(col); setSortAsc(true); }
  };

  const Arrow = ({ col }) =>
    sortBy === col ? (sortAsc ? " ↑" : " ↓") : "";

  if (loading) return <div className="page-loading"><div className="spinner" /><span>Loading…</span></div>;

  return (
    <div className="page">
      {orderStock && (
        <OrderModal
          stock={orderStock}
          headers={headers}
          onClose={() => setOrderStock(null)}
          onFilled={load}
        />
      )}

      <div className="page-header">
        <div>
          <h1>Stocks</h1>
          <div className="page-header-meta">Real-time quotes · updates every 15s</div>
        </div>
        <div className="page-header-right">
          <input
            className="search-input"
            placeholder="Search symbol or name…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="panel">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ cursor: "pointer" }} onClick={() => handleSort("sym")}>
                Symbol<Arrow col="sym" />
              </th>
              <th>Company</th>
              <th style={{ cursor: "pointer", textAlign: "right" }} onClick={() => handleSort("price")}>
                Price<Arrow col="price" />
              </th>
              <th style={{ cursor: "pointer", textAlign: "right" }} onClick={() => handleSort("chg")}>
                Change<Arrow col="chg" />
              </th>
              <th style={{ cursor: "pointer", textAlign: "right" }} onClick={() => handleSort("chgPct")}>
                % Change<Arrow col="chgPct" />
              </th>
              <th style={{ textAlign: "right" }}>Volume</th>
              <th style={{ textAlign: "right" }}>Position</th>
              <th style={{ textAlign: "center", width: 100 }}>Trade</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r) => {
              const pl = r.pos ? parseFloat(r.pos.unrealized_pl) : null;
              return (
                <tr key={r.sym}>
                  <td>
                    <span style={{ fontFamily: "var(--mono)", fontWeight: 700, fontSize: 14 }}>{r.sym}</span>
                  </td>
                  <td style={{ color: "var(--muted)" }}>{r.name}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>
                    {fmtMoney(r.price || undefined)}
                  </td>
                  <td className={r.chg >= 0 ? "green" : "red"} style={{ textAlign: "right" }}>
                    {r.price ? `${r.chg >= 0 ? "+" : ""}${r.chg.toFixed(2)}` : "—"}
                  </td>
                  <td className={r.chgPct >= 0 ? "green" : "red"} style={{ textAlign: "right" }}>
                    {r.price ? fmtPct(r.chgPct) : "—"}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--muted)", fontSize: 12 }}>
                    {r.vol > 0
                      ? r.vol >= 1e6
                        ? `${(r.vol / 1e6).toFixed(1)}M`
                        : `${(r.vol / 1e3).toFixed(0)}K`
                      : "—"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    {r.pos ? (
                      <span
                        style={{
                          fontFamily: "var(--mono)",
                          fontSize: 12,
                          fontWeight: 600,
                          color: pl >= 0 ? "var(--green)" : "var(--red)",
                          background: pl >= 0 ? "rgba(74,222,128,0.1)" : "rgba(248,113,113,0.1)",
                          padding: "2px 8px",
                          borderRadius: 5,
                        }}
                      >
                        {r.pos.qty} @ {parseFloat(r.pos.avg_entry_price).toFixed(2)}
                      </span>
                    ) : (
                      <span style={{ color: "var(--muted2)" }}>—</span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    <button
                      onClick={() => setOrderStock(r)}
                      style={{
                        padding: "5px 12px",
                        background: "rgba(96,165,250,0.1)",
                        border: "1px solid rgba(96,165,250,0.2)",
                        borderRadius: 6,
                        color: "var(--blue)",
                        fontSize: 12,
                        fontWeight: 600,
                        cursor: "pointer",
                        transition: "all 0.15s",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = "rgba(96,165,250,0.2)";
                        e.currentTarget.style.borderColor = "rgba(96,165,250,0.4)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = "rgba(96,165,250,0.1)";
                        e.currentTarget.style.borderColor = "rgba(96,165,250,0.2)";
                      }}
                    >
                      Trade
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
