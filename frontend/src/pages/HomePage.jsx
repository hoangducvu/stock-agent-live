import { useNavigate } from "react-router-dom";
import "./HomePage.css";

const FEATURES = [
  {
    icon: "◆",
    title: "Strategy-Driven Automation",
    desc: "Pick from a library of proven strategies or define your own. The bot executes every trade for you — no manual intervention needed.",
  },
  {
    icon: "◎",
    title: "Paper & Live Trading",
    desc: "Test your strategy risk-free with paper trading powered by Alpaca, then flip to live mode when you're confident.",
  },
  {
    icon: "▦",
    title: "Real-Time Dashboard",
    desc: "Monitor P&L, open positions, and trade history at a glance. Live data feeds keep you always in sync with the market.",
  },
  {
    icon: "◈",
    title: "Market Intelligence",
    desc: "Curated news feed and technical indicators surface the signals that matter, so you never trade blind.",
  },
  {
    icon: "◇",
    title: "Learn As You Go",
    desc: "Built-in learning section explains every strategy, indicator, and risk concept — from beginner to advanced.",
  },
  {
    icon: "⬡",
    title: "Secure & Non-Custodial",
    desc: "Your Alpaca credentials stay encrypted on your account. We never hold your funds or touch your positions without instruction.",
  },
];

const STEPS = [
  { n: "01", title: "Connect Alpaca", desc: "Link your Alpaca account in seconds via API key — paper or live." },
  { n: "02", title: "Choose a Strategy", desc: "Browse our strategy library or write a custom rule set in plain language." },
  { n: "03", title: "Set Risk Limits", desc: "Define max drawdown, position size, and daily loss caps before going live." },
  { n: "04", title: "Let the Bot Trade", desc: "The engine monitors markets 24/5 and executes orders the moment your conditions are met." },
];

export default function HomePage() {
  const navigate = useNavigate();

  return (
    <div className="home">
      {/* ── Nav ── */}
      <header className="home-nav">
        <div className="home-nav-inner">
          <div className="home-brand">
            <span className="home-brand-diamond">◆</span>
            <span className="home-brand-name">Nexlara</span>
          </div>
          <nav className="home-nav-links">
            <a href="#features">Features</a>
            <a href="#how-it-works">How it works</a>
            <button className="btn-nav-cta" onClick={() => navigate("/tradingbot")}>
              Launch App
            </button>
          </nav>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="home-hero">
        <div className="hero-glow" />
        <div className="hero-inner">
          <div className="hero-badge">Powered by Alpaca Markets</div>
          <h1 className="hero-headline">
            Automated trading,<br />
            <span className="hero-gradient">your strategy</span>
          </h1>
          <p className="hero-sub">
            Define a strategy, connect your brokerage, and let the bot handle every order —
            with real-time dashboards, live news, and built-in risk controls.
          </p>
          <div className="hero-actions">
            <button className="btn-primary" onClick={() => navigate("/tradingbot")}>
              Start Trading Free →
            </button>
            <a href="#how-it-works" className="btn-ghost">See how it works</a>
          </div>
          <div className="hero-stats">
            <div className="stat">
              <span className="stat-val">100+</span>
              <span className="stat-label">Strategies</span>
            </div>
            <div className="stat-divider" />
            <div className="stat">
              <span className="stat-val">24/5</span>
              <span className="stat-label">Market coverage</span>
            </div>
            <div className="stat-divider" />
            <div className="stat">
              <span className="stat-val">$0</span>
              <span className="stat-label">To get started</span>
            </div>
          </div>
        </div>

        {/* ── Mock terminal card ── */}
        <div className="hero-card">
          <div className="card-header">
            <span className="card-dot red" /><span className="card-dot amber" /><span className="card-dot green" />
            <span className="card-title">strategy_orb.py — live</span>
          </div>
          <div className="card-body">
            <div className="terminal-line"><span className="t-muted">09:31:02</span> <span className="t-green">BUY</span>  AAPL  <span className="t-val">$187.24</span> × 10</div>
            <div className="terminal-line"><span className="t-muted">09:45:18</span> <span className="t-red">SELL</span> AAPL  <span className="t-val">$188.91</span> × 10</div>
            <div className="terminal-line"><span className="t-muted">10:02:44</span> <span className="t-green">BUY</span>  NVDA  <span className="t-val">$453.10</span> × 5</div>
            <div className="terminal-line"><span className="t-muted">10:17:03</span> <span className="t-green">BUY</span>  TSLA  <span className="t-val">$249.60</span> × 8</div>
            <div className="terminal-line"><span className="t-muted">10:32:51</span> <span className="t-red">SELL</span> TSLA  <span className="t-val">$252.30</span> × 8</div>
            <div className="terminal-line blink"><span className="t-muted">10:41:07</span> <span className="t-amber">WAIT</span> — scanning…</div>
          </div>
          <div className="card-footer">
            <span className="badge-paper">◉ Paper Mode</span>
            <span className="pnl-positive">+$48.70 today</span>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section className="home-features" id="features">
        <div className="section-inner">
          <div className="section-label">Features</div>
          <h2 className="section-title">Everything you need to trade smarter</h2>
          <div className="features-grid">
            {FEATURES.map((f) => (
              <div className="feature-card" key={f.title}>
                <span className="feature-icon">{f.icon}</span>
                <h3 className="feature-title">{f.title}</h3>
                <p className="feature-desc">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ── */}
      <section className="home-steps" id="how-it-works">
        <div className="section-inner">
          <div className="section-label">How it works</div>
          <h2 className="section-title">Live in four steps</h2>
          <div className="steps-list">
            {STEPS.map((s, i) => (
              <div className="step" key={s.n}>
                <div className="step-num">{s.n}</div>
                <div className="step-body">
                  <h3 className="step-title">{s.title}</h3>
                  <p className="step-desc">{s.desc}</p>
                </div>
                {i < STEPS.length - 1 && <div className="step-connector" />}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="home-cta">
        <div className="cta-glow" />
        <div className="section-inner cta-inner">
          <h2 className="cta-title">Ready to automate your edge?</h2>
          <p className="cta-sub">Start paper trading for free. No credit card required.</p>
          <button className="btn-primary btn-lg" onClick={() => navigate("/tradingbot")}>
            Open the Trading Platform →
          </button>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="home-footer">
        <div className="home-nav-inner">
          <span className="home-brand">
            <span className="home-brand-diamond">◆</span>
            <span className="home-brand-name">Nexlara</span>
          </span>
          <span className="footer-copy">© {new Date().getFullYear()} Nexlara. All rights reserved.</span>
        </div>
      </footer>
    </div>
  );
}
