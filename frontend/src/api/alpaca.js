const BASE = "http://65.108.242.41";
const TIMEOUT_MS = 15000;

async function req(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}${path}`, { ...options, signal: controller.signal });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e.name === "AbortError") throw new Error("Request timed out. Is the backend running?");
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  validate: (body) =>
    req("/api/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  account: (headers) => req("/api/account", { headers }),
  positions: (headers) => req("/api/positions", { headers }),
  orders: (headers, status = "all", limit = 50) =>
    req(`/api/orders?status=${status}&limit=${limit}`, { headers }),
  portfolioHistory: (headers, period = "1W", timeframe = "1D") =>
    req(`/api/portfolio/history?period=${period}&timeframe=${timeframe}`, { headers }),
  quotes: (symbols, headers) =>
    req(`/api/quotes?symbols=${symbols}`, { headers }),
  placeOrder: (headers, body) =>
    req("/api/orders", {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  cancelOrder: (headers, orderId) =>
    req(`/api/orders/${orderId}`, { method: "DELETE", headers }),
  strategies: () => req("/api/strategies"),
  botStatus: () => req("/api/bot/status"),
  botStart: (body) =>
    req("/api/bot/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  botStop: (strategy) =>
    req("/api/bot/stop" + (strategy ? `?strategy=${encodeURIComponent(strategy)}` : ""), { method: "POST" }),
  bots: () => req("/api/bots"),
  testOrder: (headers, symbol = "AAPL", qty = 1, side = "buy") =>
    req("/api/bot/test-order", {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ symbol, qty, side }),
    }),
  health: () => req("/api/health"),
};
