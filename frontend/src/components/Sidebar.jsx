// Left panel: an upload form (with drag & drop) and the project list with live status.
// (User identity + logout live in the top-bar ProfileMenu.)

import { useState } from "react";
import { api } from "../api";
import { useToast } from "./Toast";

const STATUS_LABEL = {
  UPLOADING: "Uploading",
  INDEXING: "Indexing…",
  READY: "Ready",
  FAILED: "Failed",
};

function StatusBadge({ status }) {
  const spinning = status === "UPLOADING" || status === "INDEXING";
  return (
    <span className={`badge badge-${status?.toLowerCase()}`}>
      {spinning && <span className="spinner" />}
      {STATUS_LABEL[status] || status}
    </span>
  );
}

export default function Sidebar({ projects, selectedId, onSelect, onChanged, onDeleted }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const toast = useToast();

  const pickZip = (files) => {
    const zip = [...(files || [])].find((f) => f.name.toLowerCase().endsWith(".zip"));
    if (zip) {
      setFile(zip);
      setError("");
    } else {
      setError("Please choose a .zip file.");
    }
  };

  const upload = async (e) => {
    e.preventDefault();
    setError("");
    if (!name.trim()) return setError("Project name is required.");
    if (!file) return setError("Choose a .zip file.");
    setBusy(true);
    try {
      await api.uploadProject(name.trim(), file);
      setName("");
      setFile(null);
      onChanged();
      toast("Upload successful. Indexing started.", "success", 5000);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    const id = pendingDelete;
    setPendingDelete(null);
    try {
      await api.deleteProject(id);
      onDeleted(id);
      toast("Project deleted", "success");
    } catch (err) {
      toast(err.message, "error");
    }
  };

  return (
    <aside className="sidebar">
      <form className="upload" onSubmit={upload}>
        <input
          placeholder="Project name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <label
          className={`dropzone ${dragging ? "drag" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); pickZip(e.dataTransfer.files); }}
        >
          <input type="file" accept=".zip" hidden onChange={(e) => pickZip(e.target.files)} />
          <span className="small">{file ? file.name : "Drag & drop a .zip here, or click to browse"}</span>
        </label>
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
              <a
                className="del"
                onClick={(e) => { e.stopPropagation(); setPendingDelete(p.id); }}
                title="Delete"
              >×</a>
            </div>
            <div className="project-meta">
              <StatusBadge status={p.status} />
              {p.status === "FAILED" && <span className="error small">{p.failure_reason}</span>}
            </div>
          </div>
        ))}
      </div>

      {pendingDelete != null && (
        <div className="modal-overlay" onClick={() => setPendingDelete(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Delete project?</h3>
            <p className="muted small">This removes the project and its index. This can't be undone.</p>
            <div className="modal-actions">
              <button className="ghost" onClick={() => setPendingDelete(null)}>Cancel</button>
              <button className="danger" onClick={confirmDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
