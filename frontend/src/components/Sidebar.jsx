import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

const NAV = [
  { to: "/dashboard", icon: "▦", label: "Dashboard"  },
  { to: "/stocks",    icon: "◈", label: "Stocks"     },
  { to: "/strategy",  icon: "◆", label: "Strategies" },
  { to: "/news",      icon: "◎", label: "News"       },
  { to: "/learn",     icon: "◇", label: "Learn"      },
];

export default function Sidebar() {
  const { auth, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <span className="logo-diamond">◆</span>
        AutoTrader
      </div>

      <nav className="sidebar-nav">
        {NAV.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
          >
            <span className="nav-icon">{icon}</span>
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="mode-chip">
          <div className={`mode-dot${auth?.paper === false ? " live" : ""}`} />
          {auth?.paper === false ? "Live Trading" : "Paper Trading"}
        </div>
        <button
          className="btn-logout"
          onClick={() => { logout(); navigate("/"); }}
        >
          ⎋ &nbsp;Log out
        </button>
      </div>
    </aside>
  );
}
