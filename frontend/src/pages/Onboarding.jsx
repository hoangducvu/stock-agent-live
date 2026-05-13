import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { api } from "../api/alpaca";

const STEPS = [
  { id: "welcome",  title: "Welcome",        icon: "◆" },
  { id: "connect",  title: "Connect Broker", icon: "⚡" },
  { id: "mode",     title: "Trading Mode",   icon: "◎" },
  { id: "strategy", title: "Strategy",       icon: "▦" },
  { id: "stocks",   title: "Select Stocks",  icon: "◈" },
  { id: "confirm",  title: "Confirm",        icon: "✓" },
];

const PRESET_STRATEGIES = [
  { id: "ema_vwap", name: "Momentum Rider",  desc: "Follows strong price trends with EMA/VWAP signals",       risk: "medium", avgReturn: "+12.4%", winRate: "64%" },
  { id: "rsi",      name: "Mean Reversion",  desc: "Buys dips and sells rallies on range-bound stocks",        risk: "low",    avgReturn: "+8.2%",  winRate: "71%" },
  { id: "orb",      name: "Breakout Hunter", desc: "Opening range breakout — detects volume-backed breakouts", risk: "high",   avgReturn: "+18.7%", winRate: "52%" },
];

const POPULAR_STOCKS = [
  { symbol: "AAPL",  name: "Apple Inc.",      change: +1.23 },
  { symbol: "MSFT",  name: "Microsoft Corp.", change: -0.87 },
  { symbol: "GOOGL", name: "Alphabet Inc.",   change: +2.15 },
  { symbol: "AMZN",  name: "Amazon.com",      change: +0.45 },
  { symbol: "TSLA",  name: "Tesla Inc.",      change: -3.21 },
  { symbol: "NVDA",  name: "NVIDIA Corp.",    change: +5.67 },
  { symbol: "META",  name: "Meta Platforms",  change: +1.89 },
  { symbol: "AMD",   name: "Advanced Micro",  change: +2.34 },
  { symbol: "JPM",   name: "JPMorgan Chase",  change: -0.45 },
  { symbol: "V",     name: "Visa Inc.",       change: +0.78 },
  { symbol: "SPY",   name: "S&P 500 ETF",     change: +1.12 },
  { symbol: "QQQ",   name: "Nasdaq 100 ETF",  change: +1.89 },
];

export default function Onboarding() {
  const { login } = useAuth();
  const navigate  = useNavigate();

  const [step,            setStep]       = useState(0);
  const [apiKey,          setApiKey]     = useState("");
  const [secretKey,       setSecretKey]  = useState("");
  const [paper,           setPaper]      = useState(true);
  const [selectedStrategy, setStrategy] = useState(null);
  const [selectedStocks,  setStocks]    = useState([]);
  const [stockSearch,     setSearch]    = useState("");
  const [showSecret,      setShowSec]   = useState(false);
  const [loading,         setLoading]   = useState(false);
  const [error,           setError]     = useState("");
  const [account,         setAccount]   = useState(null);

  const canNext = () => {
    if (step === 1) return apiKey.length > 5 && secretKey.length > 5;
    if (step === 3) return selectedStrategy !== null;
    if (step === 4) return selectedStocks.length > 0;
    return true;
  };

  const filteredStocks = POPULAR_STOCKS.filter(
    (s) =>
      s.symbol.toLowerCase().includes(stockSearch.toLowerCase()) ||
      s.name.toLowerCase().includes(stockSearch.toLowerCase())
  );

  const toggleStock = (symbol) =>
    setStocks((prev) =>
      prev.includes(symbol) ? prev.filter((s) => s !== symbol) : [...prev, symbol]
    );

  const handleNext = async () => {
    if (!canNext()) return;
    setError("");
    if (step === 2) {
      setLoading(true);
      try {
        const data = await api.validate({ api_key: apiKey, secret_key: secretKey, paper });
        setAccount(data);
      } catch (e) {
        setError(e.message || "Connection failed.");
        return;
      } finally {
        setLoading(false);
      }
    }
    if (step === STEPS.length - 1) {
      login(apiKey, secretKey, paper, selectedStrategy, selectedStocks);
      navigate("/dashboard");
      return;
    }
    setStep((s) => s + 1);
  };

  const renderStep = () => {
    switch (step) {
      case 0:
        return (
          <div className="onb-content">
            <div className="onb-welcome-icon">◆</div>
            <h1 className="onb-welcome-title">Welcome to AutoTrader</h1>
            <p className="onb-welcome-desc">
              Set up automated trading in a few steps. Connect your broker, pick a
              strategy, and let the bots work for you.
            </p>
            <div className="onb-feature-grid">
              {[
                { icon: "⚡", label: "Automated execution" },
                { icon: "◎", label: "Paper & live modes"  },
                { icon: "▦", label: "Pre-built strategies" },
                { icon: "◈", label: "Real-time monitoring" },
              ].map((f) => (
                <div key={f.label} className="onb-feature-card">
                  <span className="onb-feature-icon">{f.icon}</span>
                  <span className="onb-feature-label">{f.label}</span>
                </div>
              ))}
            </div>
          </div>
        );

      case 1:
        return (
          <div className="onb-content">
            <h2 className="onb-step-title">Connect Your Alpaca Account</h2>
            <p className="onb-step-desc">
              Get your API keys at{" "}
              <a href="https://app.alpaca.markets" target="_blank" rel="noreferrer">
                app.alpaca.markets
              </a>
              . Keys are stored locally and never sent to our servers.
            </p>
            <div className="onb-form-group">
              <label className="onb-label">API Key</label>
              <input
                className="onb-input"
                type="text"
                placeholder="PK..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </div>
            <div className="onb-form-group">
              <label className="onb-label">API Secret</label>
              <div className="onb-input-wrap">
                <input
                  className="onb-input"
                  type={showSecret ? "text" : "password"}
                  placeholder="Enter your secret key"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  style={{ paddingRight: 40 }}
                />
                <button
                  className="onb-eye-btn"
                  type="button"
                  onClick={() => setShowSec((v) => !v)}
                >
                  {showSecret ? "◉" : "○"}
                </button>
              </div>
            </div>
            <div className="onb-security-note">
              <span style={{ color: "var(--green)" }}>⬡</span> Credentials stored
              locally — never transmitted to third parties
            </div>
          </div>
        );

      case 2:
        return (
          <div className="onb-content">
            <h2 className="onb-step-title">Choose Trading Mode</h2>
            <p className="onb-step-desc">
              Start with paper trading to test risk-free, or go live with real capital.
            </p>
            <div className="onb-mode-grid">
              <button
                className={`onb-mode-card ${paper ? "selected-paper" : ""}`}
                onClick={() => setPaper(true)}
              >
                <div className="onb-mode-icon">◇</div>
                <h3 className="onb-mode-title">Paper Trading</h3>
                <p className="onb-mode-desc">
                  Simulated trades with real market data. Zero financial risk.
                </p>
                <span className="onb-mode-badge green">Recommended</span>
              </button>
              <button
                className={`onb-mode-card ${!paper ? "selected-live" : ""}`}
                onClick={() => setPaper(false)}
              >
                <div className="onb-mode-icon">◆</div>
                <h3 className="onb-mode-title">Live Trading</h3>
                <p className="onb-mode-desc">
                  Real trades with real capital. Ensure you understand the risks.
                </p>
                <span className="onb-mode-badge amber">Advanced</span>
              </button>
            </div>
            {error && <div className="onb-error">{error}</div>}
          </div>
        );

      case 3:
        return (
          <div className="onb-content">
            <h2 className="onb-step-title">Pick a Strategy</h2>
            <p className="onb-step-desc">
              Choose a pre-built strategy to start. Customize parameters from the
              dashboard later.
            </p>
            <div className="onb-strategy-list">
              {PRESET_STRATEGIES.map((s) => (
                <button
                  key={s.id}
                  className={`onb-strategy-card ${selectedStrategy === s.id ? "selected" : ""}`}
                  onClick={() => setStrategy(s.id)}
                >
                  <div className="onb-strategy-header">
                    <span className="onb-strategy-name">{s.name}</span>
                    <span className={`risk-badge ${s.risk}`}>
                      {s.risk.charAt(0).toUpperCase() + s.risk.slice(1)} Risk
                    </span>
                  </div>
                  <p className="onb-strategy-desc">{s.desc}</p>
                  <div className="onb-strategy-stats">
                    <span>
                      Avg Return:{" "}
                      <b style={{ color: "var(--green)" }}>{s.avgReturn}</b>
                    </span>
                    <span>
                      Win Rate:{" "}
                      <b style={{ color: "var(--blue)" }}>{s.winRate}</b>
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        );

      case 4:
        return (
          <div className="onb-content">
            <h2 className="onb-step-title">Select Stocks to Trade</h2>
            <p className="onb-step-desc">
              Pick the stocks your bot will monitor and trade. Change these anytime.
            </p>
            <input
              className="onb-input"
              style={{ marginBottom: 16, fontFamily: "var(--sans)" }}
              type="text"
              placeholder="Search stocks..."
              value={stockSearch}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="onb-stock-grid">
              {filteredStocks.map((s) => (
                <button
                  key={s.symbol}
                  className={`onb-stock-card ${selectedStocks.includes(s.symbol) ? "selected" : ""}`}
                  onClick={() => toggleStock(s.symbol)}
                >
                  <div className="onb-stock-symbol">{s.symbol}</div>
                  <div className="onb-stock-name">{s.name}</div>
                  <div
                    className="onb-stock-change"
                    style={{ color: s.change >= 0 ? "var(--green)" : "var(--red)" }}
                  >
                    {s.change >= 0 ? "+" : ""}{s.change}%
                  </div>
                </button>
              ))}
            </div>
            <div style={{ marginTop: 12, color: "rgba(255,255,255,0.4)", fontSize: 13 }}>
              {selectedStocks.length} stock{selectedStocks.length !== 1 ? "s" : ""} selected
            </div>
          </div>
        );

      case 5:
        return (
          <div className="onb-content">
            <h2 className="onb-step-title">Review & Confirm</h2>
            <p className="onb-step-desc">Everything looks good? Let's launch.</p>
            <div className="onb-summary-grid">
              <div className="onb-summary-card">
                <div className="onb-summary-label">Broker</div>
                <div className="onb-summary-value">Alpaca</div>
                <div className="onb-summary-sub" style={{ color: "var(--green)" }}>
                  {account ? "Connected ✓" : "Ready"}
                </div>
              </div>
              <div className="onb-summary-card">
                <div className="onb-summary-label">Mode</div>
                <div className="onb-summary-value">
                  {paper ? "Paper Trading" : "Live Trading"}
                </div>
                <div
                  className="onb-summary-sub"
                  style={{ color: paper ? "var(--green)" : "var(--amber)" }}
                >
                  {paper ? "Simulated" : "Real Capital"}
                </div>
              </div>
              <div className="onb-summary-card">
                <div className="onb-summary-label">Strategy</div>
                <div className="onb-summary-value">
                  {PRESET_STRATEGIES.find((s) => s.id === selectedStrategy)?.name || "—"}
                </div>
                <div className="onb-summary-sub">
                  {PRESET_STRATEGIES.find((s) => s.id === selectedStrategy)?.winRate} win rate
                </div>
              </div>
              <div className="onb-summary-card">
                <div className="onb-summary-label">Stocks</div>
                <div className="onb-summary-value">{selectedStocks.length} selected</div>
                <div className="onb-summary-sub">{selectedStocks.slice(0, 4).join(", ")}{selectedStocks.length > 4 ? "…" : ""}</div>
              </div>
              {account && (
                <div className="onb-summary-card" style={{ gridColumn: "span 2" }}>
                  <div className="onb-summary-label">Portfolio Value</div>
                  <div className="onb-summary-value" style={{ color: "var(--green)" }}>
                    ${parseFloat(account.portfolio_value || 0).toFixed(2)}
                  </div>
                  <div className="onb-summary-sub">
                    Buying power: ${parseFloat(account.buying_power || 0).toFixed(2)}
                  </div>
                </div>
              )}
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="onboarding-layout">
      <div className="onb-sidebar">
        <div className="onb-logo">◆ AutoTrader</div>
        <div className="onb-steps">
          {STEPS.map((s, i) => (
            <div key={s.id} className={`onb-step ${i > step ? "future" : ""}`}>
              <div
                className={`onb-step-dot ${
                  i < step ? "done" : i === step ? "current" : "future"
                }`}
              >
                {i < step ? "✓" : s.icon}
              </div>
              <span className="onb-step-label">{s.title}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="onb-main">
        {renderStep()}
        <div className="onb-actions">
          {step > 0 && (
            <button
              className="btn-ghost"
              onClick={() => { setError(""); setStep((s) => s - 1); }}
            >
              Back
            </button>
          )}
          <button
            className="btn-primary"
            style={{
              opacity: canNext() ? 1 : 0.4,
              cursor: canNext() ? "pointer" : "not-allowed",
            }}
            onClick={handleNext}
            disabled={loading || !canNext()}
          >
            {loading ? (
              <span className="btn-spinner" />
            ) : step === STEPS.length - 1 ? (
              "Launch Dashboard"
            ) : (
              "Continue"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
