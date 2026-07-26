// Thin API client. All calls attach the JWT (if present) and surface backend {error} messages.
// Streaming uses fetch + ReadableStream (not EventSource) because the SSE endpoint is a POST
// that needs the Authorization header.

const API = import.meta.env.VITE_API_URL || ""; // "" in dev -> Vite proxies /api to the backend

function authHeaders() {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handle(res) {
  if (!res.ok) {
    let message = "Request failed";
    try {
      message = (await res.json()).error || message;
    } catch {
      /* non-JSON error */
    }
    throw new Error(message);
  }
  return res.json();
}

function jsonPost(path, body) {
  return fetch(`${API}${path}`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(handle);
}

export const api = {
  register: (name, email, password) =>
    jsonPost("/api/auth/register", { name, email, password }),
  login: (email, password) => jsonPost("/api/auth/login", { email, password }),
  me: () => fetch(`${API}/api/auth/me`, { headers: authHeaders() }).then(handle),

  listProjects: () => fetch(`${API}/api/projects`, { headers: authHeaders() }).then(handle),
  getProject: (id) => fetch(`${API}/api/projects/${id}`, { headers: authHeaders() }).then(handle),
  deleteProject: (id) =>
    fetch(`${API}/api/projects/${id}`, { method: "DELETE", headers: authHeaders() }).then(handle),
  uploadProject: (name, file) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("file", file);
    return fetch(`${API}/api/projects`, {
      method: "POST",
      headers: authHeaders(),
      body: fd,
    }).then(handle);
  },

  history: (id) => fetch(`${API}/api/projects/${id}/chats`, { headers: authHeaders() }).then(handle),

  // Consume the SSE stream frame-by-frame, dispatching typed events to callbacks.
  askStream: async (id, question, { onMeta, onToken, onDone, onError, signal }) => {
    let res;
    try {
      res = await fetch(`${API}/api/projects/${id}/ask/stream`, {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal,
      });
    } catch (e) {
      if (e.name === "AbortError") return; // user stopped generation
      onError(`Network error: ${e.message}`);
      return;
    }
    if (!res.ok) {
      let message = "Request failed";
      try {
        message = (await res.json()).error || message;
      } catch {
        /* ignore */
      }
      onError(message);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const line = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          let evt;
          try {
            evt = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }
          if (evt.type === "meta") onMeta?.(evt);
          else if (evt.type === "token") onToken?.(evt.text);
          else if (evt.type === "done") onDone?.(evt);
          else if (evt.type === "error") onError?.(evt.error);
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") onError?.(`Stream error: ${e.message}`);
    }
  },
};
