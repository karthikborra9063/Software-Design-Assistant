// Chat view: loads history and streams answers token-by-token, rendered as Markdown.
// Source file locations appear inline in the answer (the model's "Implemented in …" line).

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Markdown from "./Markdown";
import { useToast } from "./Toast";

export default function Chat({ project }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const endRef = useRef(null);
  const abortRef = useRef(null);
  const toast = useToast();

  // Load history when the selected project changes.
  useEffect(() => {
    setMessages([]);
    if (project.status !== "READY") return;
    api.history(project.id).then(({ chats }) => {
      const msgs = [];
      chats.forEach((c) => {
        msgs.push({ role: "user", content: c.question });
        msgs.push({ role: "assistant", content: c.answer || "" });
      });
      setMessages(msgs);
    });
  }, [project.id, project.status]);

  useEffect(() => {
    // Instant (not smooth) so rapid token updates don't stutter the scroll.
    endRef.current?.scrollIntoView({ behavior: "auto" });
  }, [messages]);

  const patchLast = (patch) =>
    setMessages((m) => {
      const copy = [...m];
      copy[copy.length - 1] = { ...copy[copy.length - 1], ...patch };
      return copy;
    });

  const send = async () => {
    const q = input.trim();
    if (!q || streaming) return;
    setInput("");
    setMessages((m) => [
      ...m,
      { role: "user", content: q },
      { role: "assistant", content: "", streaming: true },
    ]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    await api.askStream(project.id, q, {
      signal: controller.signal,
      onToken: (t) =>
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          copy[copy.length - 1] = { ...last, content: last.content + t };
          return copy;
        }),
      onDone: () => patchLast({ streaming: false }),
      onError: (err) =>
        setMessages((m) => {
          const copy = [...m];
          const last = copy[copy.length - 1];
          const prefix = last.content ? last.content + "\n\n" : "";
          copy[copy.length - 1] = { ...last, streaming: false, content: `${prefix}⚠️ ${err}` };
          return copy;
        }),
    });

    abortRef.current = null;
    patchLast({ streaming: false }); // also covers a user-initiated stop
    setStreaming(false);
  };

  const stop = () => abortRef.current?.abort();

  const copyAnswer = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      toast("Answer copied", "success");
    } catch {
      toast("Copy failed", "error");
    }
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
              {m.role === "assistant" && !m.streaming && m.content && (
                <button className="answer-copy" onClick={() => copyAnswer(m.content)}>Copy</button>
              )}
              {m.role === "assistant" ? (
                m.streaming ? (
                  // While streaming, render raw text (no per-token Markdown re-parse/
                  // re-highlight flicker); switch to full Markdown once the answer completes.
                  <div className="streaming-text">{m.content}<span className="cursor" /></div>
                ) : (
                  <Markdown>{m.content}</Markdown>
                )
              ) : (
                m.content
              )}
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
          {streaming ? (
            <button className="stop" onClick={stop}>Stop</button>
          ) : (
            <button className="primary" onClick={send} disabled={!input.trim()}>Ask</button>
          )}
        </div>
      )}
    </div>
  );
}
