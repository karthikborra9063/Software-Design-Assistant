// Auth state: holds the current user, persists the JWT in localStorage, and validates it on
// load via /api/auth/me.

import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false); // false until we've checked any stored token

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      setReady(true);
      return;
    }
    api
      .me()
      .then((d) => setUser(d.user))
      .catch(() => localStorage.removeItem("token"))
      .finally(() => setReady(true));
  }, []);

  const login = async (email, password) => {
    const d = await api.login(email, password);
    localStorage.setItem("token", d.access_token);
    setUser(d.user);
  };

  const register = async (name, email, password) => {
    const d = await api.register(name, email, password);
    localStorage.setItem("token", d.access_token);
    setUser(d.user);
  };

  const logout = () => {
    localStorage.removeItem("token");
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, ready, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
