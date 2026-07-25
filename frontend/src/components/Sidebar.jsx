// Left panel: user identity + logout, an upload form, and the project list with live status.

import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../AuthContext";

const STATUS_LABEL = {
  UPLOADING: "Uploading",
  INDEXING: "Indexing…",
  READY: "Ready",
  FAILED: "Failed",
};

function StatusBadge({ status }) {
  return <span className={`badge badge-${status?.toLowerCase()}`}>{STATUS_LABEL[status] || status}</span>;
}

export default function Sidebar({ projects, selectedId, onSelect, onChanged, onDeleted }) {
  const { user, logout } = useAuth();
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const upload = async (e) => {
    e.preventDefault();
    setError("");
    if (!file) return setError("Choose a .zip file.");
    setBusy(true);
    try {
      await api.uploadProject(name || file.name.replace(/\.zip$/i, ""), file);
      setName("");
      setFile(null);
      e.target.reset();
      onChanged();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id, e) => {
    e.stopPropagation();
    if (!confirm("Delete this project and its index?")) return;
    try {
      await api.deleteProject(id);
      onDeleted(id);
    } catch (err) {
      alert(err.message);
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <h1 className="brand">aiRA</h1>
        <div className="user">
          <span className="muted small">{user?.email}</span>
          <a className="small" onClick={logout}>Log out</a>
        </div>
      </div>

      <form className="upload" onSubmit={upload}>
        <input
          placeholder="Project name (optional)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input type="file" accept=".zip" onChange={(e) => setFile(e.target.files[0])} />
        {error && <div className="error small">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Uploading…" : "Upload project"}</button>
      </form>

      <div className="projects">
        {projects.length === 0 && <p className="muted small pad">No projects yet.</p>}
        {projects.map((p) => (
          <div
            key={p.id}
            className={`project ${p.id === selectedId ? "active" : ""}`}
            onClick={() => onSelect(p.id)}
          >
            <div className="project-top">
              <span className="project-name">{p.name}</span>
              <a className="del" onClick={(e) => remove(p.id, e)} title="Delete">×</a>
            </div>
            <div className="project-meta">
              <StatusBadge status={p.status} />
              {p.status === "READY" && (
                <span className="muted small">
                  {p.total_files} files · {p.total_chunks} chunks{p.language ? ` · ${p.language}` : ""}
                </span>
              )}
              {p.status === "FAILED" && <span className="error small">{p.failure_reason}</span>}
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
