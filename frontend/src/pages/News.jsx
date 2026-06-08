import { useState, useEffect, useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../api/alpaca";

const POLL_MS = 60000;

const UNIVERSE_SYMBOLS = [
  "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","JPM","V","MA",
  "AMD","INTC","BAC","F","PLTR","SOFI","SNAP","NIO","COIN","UBER",
  "SPY","QQQ","NFLX","DIS","CRM","SHOP","PYPL","ORCL","BABA","RIVN",
].join(",");

function relTime(iso) {
  if (!iso) return "—";
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return "—";
  const diff = Math.max(0, (Date.now() - ts) / 1000);
  if (diff < 60)    return `${Math.floor(diff)}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function News() {
  const { headers } = useAuth();
  const [articles,   setArticles]   = useState([]);
  const [search,     setSearch]     = useState("");
  const [expanded,   setExpanded]   = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState("");

  const load = useCallback(async () => {
    try {
      const data = await api.news(headers, UNIVERSE_SYMBOLS, 40);
      const items = (data?.news || []).map((n) => ({
        id:        n.id,
        title:     n.headline,
        summary:   n.summary || "",
        source:    n.source || "—",
        url:       n.url,
        created:   n.created_at || n.updated_at,
        tickers:   (n.symbols || []).slice(0, 4),
      }));
      setArticles(items);
      setLastUpdate(new Date());
      setError("");
    } catch (e) {
      setError(e.message || "Failed to load news");
    } finally {
      setLoading(false);
    }
  }, [headers]);

  useEffect(() => {
    load();
    const iv = setInterval(load, POLL_MS);
    return () => clearInterval(iv);
  }, [load]);

  const filtered = articles.filter((n) => {
    const q = search.toLowerCase();
    if (!q) return true;
    return (
      n.title.toLowerCase().includes(q) ||
      n.source.toLowerCase().includes(q) ||
      n.tickers.some((t) => t.toLowerCase().includes(q))
    );
  });

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>News</h1>
          <div className="page-header-meta">
            Live market news · refreshes every 60s
            {lastUpdate && ` · last update ${lastUpdate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}`}
          </div>
        </div>
        <div className="page-header-right">
          <input
            className="search-input"
            placeholder="Search news or ticker…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            onClick={load}
            style={{
              padding: "7px 14px", background: "rgba(96,165,250,0.1)",
              border: "1px solid rgba(96,165,250,0.25)", borderRadius: 6,
              color: "var(--blue)", fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}
          >Refresh</button>
        </div>
      </div>

      <div style={{ marginBottom: 14, fontSize: 12, color: "var(--muted)" }}>
        {filtered.length} article{filtered.length !== 1 ? "s" : ""}
        {error && <span style={{ color: "var(--red)", marginLeft: 12 }}>⚠ {error}</span>}
      </div>

      {loading ? (
        <div className="page-loading"><div className="spinner" /><span>Loading news…</span></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.length === 0 ? (
            <div className="panel"><div className="empty-state">No articles match your search.</div></div>
          ) : filtered.map((article) => (
            <div
              key={article.id}
              className="panel"
              style={{ cursor: "pointer", transition: "background 0.2s" }}
              onClick={() => setExpanded(expanded === article.id ? null : article.id)}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <div style={{ width: 3, borderRadius: 2, alignSelf: "stretch", flexShrink: 0, background: "var(--blue)", minHeight: 40 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>{article.source}</span>
                    <span style={{ fontSize: 12, color: "var(--muted2)" }}>·</span>
                    <span style={{ fontSize: 12, color: "var(--muted2)" }}>{relTime(article.created)}</span>
                    <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
                      {article.tickers.map((t) => (
                        <span key={t} className="stock-tag">{t}</span>
                      ))}
                    </div>
                  </div>

                  <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.4, marginBottom: expanded === article.id ? 10 : 0 }}>
                    {article.title}
                  </div>

                  {expanded === article.id && (
                    <>
                      {article.summary && (
                        <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.6, marginTop: 8 }}>
                          {article.summary}
                        </div>
                      )}
                      {article.url && (
                        <a
                          href={article.url} target="_blank" rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          style={{ display: "inline-block", marginTop: 10, fontSize: 12, color: "var(--blue)" }}
                        >Read full article →</a>
                      )}
                    </>
                  )}
                </div>

                <div style={{
                  fontSize: 11, color: "var(--muted2)", flexShrink: 0,
                  transform: expanded === article.id ? "rotate(180deg)" : "none",
                  transition: "transform 0.2s", marginTop: 2,
                }}>▾</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
