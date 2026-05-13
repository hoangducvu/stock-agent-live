import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import Sidebar from "./components/Sidebar";
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
  if (!auth) return <Navigate to="/" replace />;
  return <AppLayout />;
}

function RootRedirect() {
  const { auth } = useAuth();
  return <Navigate to={auth ? "/dashboard" : "/"} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Onboarding />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/stocks"    element={<Stocks />} />
            <Route path="/strategy"  element={<Strategy />} />
            <Route path="/news"      element={<News />} />
            <Route path="/learn"     element={<Learn />} />
          </Route>
          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
