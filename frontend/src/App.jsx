import { useAuth } from "./AuthContext";
import Auth from "./components/Auth";
import Dashboard from "./components/Dashboard";

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) return <div className="center muted">Loading…</div>;
  return user ? <Dashboard /> : <Auth />;
}
