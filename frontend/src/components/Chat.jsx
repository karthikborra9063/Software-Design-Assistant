// Chat view: loads history, streams answers token-by-token, and shows citations + a short
// "why these sources" note under each answer.

import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export default function Chat({ project }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const endRef = useRef(null);

  // Load history when the selected project changes.
  useEffect(() => {
    setMessages([]);
    if (project.status !== "READY") return;
    api.history(project.id).then(({ chats }) => {
      const msgs = [];
      chats.forEach((c) => {
        msgs.push({ role: "user", content: c.question });
        msgs.push({ role: "assistant", content: c.answer || "", citations: c.citations || [] });
      });
      setMessages(msgs);
    });
  }, [project.id, project.status]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput("");
    setMessages((m) => [
      ...m,
      { role: "user", content: q },
      { role: "assistant", content: "", citations: [], explanation: "", streaming: true },
    ]);
    setStreaming(true);

    const patchLast = (patch) =>
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
        return copy;
      });

    await api.askStream(project.id, q, {
      onMeta: (e) => patchLast({ citations: e.citations, explanation: e.explanation }),
      onToken: (t) =>
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, content: last.content + t };
          return copy;
        }),
      onDone: (e) => patchLast({ streaming: false, model: e.model }),
      onError: (err) =>
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          const prefix = last.content ? last.content + "\n\n" : "";
          copy[copy.length - 1] = { ...last, streaming: false, content: `${prefix}⚠️ ${err}` };
          return copy;
        }),
    });
    setStreaming(false);
  };

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  const notReady = project.status !== "READY";

  return (
    <div className="chat">
      <header className="chat-head">
        <h2>{project.name}</h2>
        <span className="muted small">{project.language || "project"} · {project.total_chunks} chunks</span>
      </header>

      <div className="messages">
        {messages.length === 0 && !notReady && (
          <div className="muted center-soft">
            <p>Ask anything — e.g. “How does authentication work?”, “Explain the architecture”,
              “Which files handle uploads?”</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="bubble">
              {m.content || (m.streaming ? <span className="muted">…</span> : "")}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {notReady ? (
        <div className="composer disabled muted">
          {project.status === "FAILED"
            ? `Indexing failed: ${project.failure_reason || "unknown error"}`
            : "Project is still indexing — questions will be enabled when it's ready."}
        </div>
      ) : (
        <div className="composer">
          <textarea
            rows={1}
            placeholder="Ask about this codebase…  (Enter to send, Shift+Enter for newline)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
          />
          <button className="primary" onClick={send} disabled={streaming || !input.trim()}>
            {streaming ? "…" : "Ask"}
          </button>
        </div>
      )}
    </div>
  );
}
