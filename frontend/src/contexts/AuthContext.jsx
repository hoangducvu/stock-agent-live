import { createContext, useContext, useState, useEffect } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState(() => {
    try {
      const saved = localStorage.getItem("stockagent_auth");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (auth) {
      localStorage.setItem("stockagent_auth", JSON.stringify(auth));
    } else {
      localStorage.removeItem("stockagent_auth");
    }
  }, [auth]);

  const login = (apiKey, secretKey, paper, strategy = null, stocks = []) => {
    setAuth({ apiKey, secretKey, paper, strategy, stocks });
  };

  const logout = () => setAuth(null);

  const headers = auth
    ? {
        "x-api-key": auth.apiKey,
        "x-secret-key": auth.secretKey,
        "x-paper": String(auth.paper),
        "Content-Type": "application/json",
      }
    : {};

  return (
    <AuthContext.Provider value={{ auth, login, logout, headers }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
