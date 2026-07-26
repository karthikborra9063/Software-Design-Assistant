// Top-right user avatar: a circle showing the user's initial; clicking it opens a dropdown
// with the user's name, email, and a logout button. Closes on outside click.

import { useEffect, useRef, useState } from "react";
import { useAuth } from "../AuthContext";

export default function ProfileMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();

  // Close the dropdown when clicking anywhere outside it.
  useEffect(() => {
    const onDocClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  return (
    <div className="profile" ref={ref}>
      <button
        className="avatar"
        onClick={() => setOpen((o) => !o)}
        title={user?.name || "Account"}
        aria-label="Account menu"
      >
        {initial}
      </button>
      {open && (
        <div className="profile-menu">
          <div className="profile-name">{user?.name}</div>
          <div className="profile-email muted small">{user?.email}</div>
          <button className="logout-btn" onClick={logout}>Log out</button>
        </div>
      )}
    </div>
  );
}
