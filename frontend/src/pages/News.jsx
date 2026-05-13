import { useState, useEffect } from "react";
import { useAuth } from "../contexts/AuthContext";

const CATEGORIES = ["All", "Markets", "Tech", "Economy", "Crypto", "Earnings"];

const MOCK_NEWS = [
  {
    id: 1, category: "Markets",
    title: "S&P 500 Climbs to Fresh Highs as Earnings Season Kicks Off",
    source: "Bloomberg", time: "2h ago",
    summary: "The benchmark index rose 0.8% driven by strong bank earnings and easing inflation data, with technology and financial sectors leading gains.",
    tickers: ["SPY", "QQQ", "JPM"],
    sentiment: "positive",
  },
  {
    id: 2, category: "Tech",
    title: "NVIDIA Reports Record Data Center Revenue, Beats Estimates by 15%",
    source: "Reuters", time: "3h ago",
    summary: "NVIDIA's Q3 revenue surged 122% YoY to $18.1B, fueled by insatiable AI chip demand. Management raised full-year guidance above consensus.",
    tickers: ["NVDA"],
    sentiment: "positive",
  },
  {
    id: 3, category: "Economy",
    title: "Fed Minutes Signal Patience on Rate Cuts; Two More Hikes Possible",
    source: "WSJ", time: "4h ago",
    summary: "Federal Reserve officials expressed concern over persistent services inflation, suggesting the central bank is in no rush to pivot despite cooling goods prices.",
    tickers: ["SPY", "TLT"],
    sentiment: "negative",
  },
  {
    id: 4, category: "Tech",
    title: "Apple Eyes AI-Powered Siri Overhaul for WWDC 2025",
    source: "The Information", time: "5h ago",
    summary: "Sources say Apple plans a comprehensive Siri rewrite using on-device large language models, potentially the biggest update to the assistant since its 2011 launch.",
    tickers: ["AAPL"],
    sentiment: "positive",
  },
  {
    id: 5, category: "Earnings",
    title: "Microsoft Azure Growth Reaccelerates to 33% in Q2",
    source: "CNBC", time: "6h ago",
    summary: "Microsoft's cloud unit returned to accelerating growth as Copilot AI seats expanded rapidly. EPS beat by $0.17, shares up 5% after-hours.",
    tickers: ["MSFT"],
    sentiment: "positive",
  },
  {
    id: 6, category: "Markets",
    title: "VIX Spikes 12% as Middle East Tensions Rattle Energy Markets",
    source: "FT", time: "7h ago",
    summary: "Volatility jumped as oil prices surged above $90/barrel. Defensive sectors outperformed while high-beta growth names sold off sharply.",
    tickers: ["SPY", "AMD", "META"],
    sentiment: "negative",
  },
  {
    id: 7, category: "Earnings",
    title: "Meta Platforms Posts 24% Revenue Growth, Doubles AI Capex Forecast",
    source: "Reuters", time: "8h ago",
    summary: "Meta's advertising recovery continued strongly. The company raised its 2025 capital expenditure guidance to $65B, citing massive AI infrastructure build-out.",
    tickers: ["META"],
    sentiment: "positive",
  },
  {
    id: 8, category: "Crypto",
    title: "Bitcoin ETF Inflows Reach $2.1B in Single Day",
    source: "CoinDesk", time: "9h ago",
    summary: "Spot Bitcoin ETFs attracted record single-day inflows as institutional adoption accelerated, pushing BTC above $72,000 for the first time in 2024.",
    tickers: ["COIN"],
    sentiment: "positive",
  },
  {
    id: 9, category: "Tech",
    title: "AMD Launches MI350 GPU to Challenge NVIDIA's Blackwell Dominance",
    source: "Tom's Hardware", time: "11h ago",
    summary: "Advanced Micro Devices unveiled its next-generation AI accelerator claiming 40% better performance-per-watt versus the H100. Cloud providers are reportedly evaluating.",
    tickers: ["AMD", "NVDA"],
    sentiment: "positive",
  },
  {
    id: 10, category: "Economy",
    title: "US Jobs Report Crushes Estimates; Unemployment Holds at 3.7%",
    source: "MarketWatch", time: "1d ago",
    summary: "Nonfarm payrolls added 303K jobs in March, nearly double expectations, reinforcing the Fed's cautious stance on rate cuts and boosting the dollar.",
    tickers: ["SPY", "DXY"],
    sentiment: "neutral",
  },
];

const SENTIMENT_COLOR = {
  positive: "var(--green)",
  negative: "var(--red)",
  neutral:  "var(--muted)",
};

const SENTIMENT_BG = {
  positive: "rgba(74,222,128,0.08)",
  negative: "rgba(248,113,113,0.08)",
  neutral:  "rgba(255,255,255,0.04)",
};

export default function News() {
  const [category,  setCategory]  = useState("All");
  const [search,    setSearch]    = useState("");
  const [expanded,  setExpanded]  = useState(null);
  const [lastUpdate, setLastUpdate] = useState(new Date());

  // Simulate live "last updated" counter
  useEffect(() => {
    const iv = setInterval(() => setLastUpdate(new Date()), 60000);
    return () => clearInterval(iv);
  }, []);

  const filtered = MOCK_NEWS.filter((n) => {
    const matchCat = category === "All" || n.category === category;
    const matchSearch =
      n.title.toLowerCase().includes(search.toLowerCase()) ||
      n.source.toLowerCase().includes(search.toLowerCase()) ||
      n.tickers.some((t) => t.toLowerCase().includes(search.toLowerCase()));
    return matchCat && matchSearch;
  });

  return (
    <div className="page">
      {/* Header */}
      <div className="page-header">
        <div>
          <h1>News</h1>
          <div className="page-header-meta">
            Market news & sentiment · Updated {lastUpdate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
        <div className="page-header-right">
          <input
            className="search-input"
            placeholder="Search news or ticker…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* Category filter */}
      <div style={{ display: "flex", gap: 6, marginBottom: 20, flexWrap: "wrap" }}>
        {CATEGORIES.map((c) => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            style={{
              padding: "6px 14px",
              border: "1px solid",
              borderColor: category === c ? "var(--blue)" : "var(--border)",
              borderRadius: 20,
              background: category === c ? "rgba(96,165,250,0.1)" : "transparent",
              color: category === c ? "var(--blue)" : "var(--muted)",
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.15s",
            }}
          >
            {c}
          </button>
        ))}
        <div style={{ marginLeft: "auto", fontSize: 12, color: "var(--muted)", alignSelf: "center" }}>
          {filtered.length} article{filtered.length !== 1 ? "s" : ""}
        </div>
      </div>

      {/* News list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {filtered.length === 0 ? (
          <div className="panel">
            <div className="empty-state">No articles match your search.</div>
          </div>
        ) : (
          filtered.map((article) => (
            <div
              key={article.id}
              className="panel"
              style={{
                cursor: "pointer",
                background: expanded === article.id ? SENTIMENT_BG[article.sentiment] : undefined,
                transition: "background 0.2s",
              }}
              onClick={() => setExpanded(expanded === article.id ? null : article.id)}
            >
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                {/* Sentiment indicator */}
                <div
                  style={{
                    width: 3, borderRadius: 2, alignSelf: "stretch", flexShrink: 0,
                    background: SENTIMENT_COLOR[article.sentiment],
                    minHeight: 40,
                  }}
                />

                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    <span style={{
                      fontSize: 11, fontWeight: 600, padding: "2px 8px", borderRadius: 4,
                      background: "rgba(96,165,250,0.1)", color: "var(--blue)",
                    }}>
                      {article.category}
                    </span>
                    <span style={{ fontSize: 12, color: "var(--muted)" }}>{article.source}</span>
                    <span style={{ fontSize: 12, color: "var(--muted2)" }}>·</span>
                    <span style={{ fontSize: 12, color: "var(--muted2)" }}>{article.time}</span>
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
                    <div style={{ fontSize: 13, color: "var(--muted)", lineHeight: 1.6, marginTop: 8 }}>
                      {article.summary}
                    </div>
                  )}
                </div>

                <div style={{
                  fontSize: 11, color: "var(--muted2)", flexShrink: 0,
                  transform: expanded === article.id ? "rotate(180deg)" : "none",
                  transition: "transform 0.2s", marginTop: 2,
                }}>
                  ▾
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
