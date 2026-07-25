// Top-level app shell: sidebar (projects + upload) on the left, chat on the right.
// Polls project statuses while any project is still indexing.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import Chat from "./Chat";
import Sidebar from "./Sidebar";

export default function Dashboard() {
  const [projects, setProjects] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const pollRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const { projects } = await api.listProjects();
      setProjects(projects);
      return projects;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll every 4s while anything is indexing, so status badges update live.
  useEffect(() => {
    const anyIndexing = projects.some((p) => ["UPLOADING", "INDEXING"].includes(p.status));
    clearInterval(pollRef.current);
    if (anyIndexing) pollRef.current = setInterval(refresh, 4000);
    return () => clearInterval(pollRef.current);
  }, [projects, refresh]);

  const selected = projects.find((p) => p.id === selectedId) || null;

  return (
    <div className="layout">
      <Sidebar
        projects={projects}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onChanged={refresh}
        onDeleted={(id) => {
          if (id === selectedId) setSelectedId(null);
          refresh();
        }}
      />
      <main className="main">
        {selected ? (
          <Chat project={selected} />
        ) : (
          <div className="center muted">
            <div>
              <h2>Select or upload a project</h2>
              <p>Upload a codebase (.zip) on the left, then ask questions once it's ready.</p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
