import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import Sidebar from "./components/Sidebar";
import HomePage from "./pages/HomePage";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import Stocks from "./pages/Stocks";
import Strategy from "./pages/Strategy";
import News from "./pages/News";
import Learn from "./pages/Learn";
import "./index.css";

function AppLayout() {
  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}

function ProtectedRoute() {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/tradingbot" replace />;
  return <AppLayout />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* ── Main homepage ── */}
          <Route path="/" element={<HomePage />} />

          {/* ── Trading bot onboarding/login ── */}
          <Route path="/tradingbot" element={<Onboarding />} />

          {/* ── Trading bot protected pages ── */}
          <Route element={<ProtectedRoute />}>
            <Route path="/tradingbot/dashboard" element={<Dashboard />} />
            <Route path="/tradingbot/stocks"    element={<Stocks />} />
            <Route path="/tradingbot/strategy"  element={<Strategy />} />
            <Route path="/tradingbot/news"      element={<News />} />
            <Route path="/tradingbot/learn"     element={<Learn />} />
          </Route>

          {/* ── Fallback ── */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
