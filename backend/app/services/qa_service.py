"""Q&A orchestration (HLD-v2 §2/§5).

Ties retrieval → prompt → LLM together with LCEL, builds the citations/evidence that make
answers explainable, and persists each turn. Exposes a blocking `answer()` and a generator
`answer_stream()` that emits Server-Sent Events (SSE).

Conversation memory is handled the standard LangChain way: when there are prior turns, a cheap
model reformulates the latest (possibly referential) message into a standalone search query,
and the recent turns are replayed to the answering model as chat history. A self-contained
question is returned unchanged by the reformulator, so single-shot Q&A is unaffected.
"""

import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from ..config import Config
from ..errors import ApiError
from ..extensions import db
from ..models import Chat, Project, ProjectStatus
from . import llm as llm_module
from .prompt_builder import ANSWER_PROMPT, format_context, history_messages
from .retrieval_service import RetrievalResult, retrieve

_MAX_QUESTION_CHARS = 2000

# ---- Conversation memory (history-aware query reformulation) ----------------------------

_REFORMULATE_SYSTEM = (
    "You rewrite the user's latest message into a single standalone search query for a "
    "code-search engine, using the chat history ONLY to resolve references.\n"
    "Rules:\n"
    "- Resolve pronouns ('it', 'that', 'they') and elliptical phrases to the concrete subject "
    "from the history.\n"
    "- Apply corrections: 'no, I meant X' means the user now wants X.\n"
    "- PRESERVE the specific nouns and technical terms the user wrote (e.g. 'messages', "
    "'database', 'schema'). NEVER generalize a specific question into a vague topic.\n"
    "- If the latest message is already a complete, self-contained question, return it "
    "essentially unchanged.\n"
    "- Output ONLY the query: no quotes, no explanation.\n"
    "Examples:\n"
    "History: how does the caching layer work | Latest: what about its expiry"
    " -> caching layer expiry\n"
    "History: explain the login page | Latest: no, I meant the registration"
    " -> registration page\n"
    "History: how does the chat feature work | Latest: how are the messages stored in the database"
    " -> how are chat messages stored in the database"
)
_REFORMULATE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _REFORMULATE_SYSTEM),
        MessagesPlaceholder("history"),
        ("human", "{question}"),
    ]
)


def _recent_turns(user_id: int, project_id: int) -> list[Chat]:
    """The last HISTORY_WINDOW turns for this user+project, oldest-first."""
    rows = (
        Chat.query.filter_by(user_id=user_id, project_id=project_id)
        .order_by(Chat.created_at.desc())
        .limit(Config.HISTORY_WINDOW)
        .all()
    )
    return list(reversed(rows))


def _reformulate(history_msgs: list, question: str) -> str:
    """Turn a follow-up into a standalone search query. Falls back to the raw question."""
    if not history_msgs:
        return question
    chain = _REFORMULATE_PROMPT | llm_module.get_planner_llm() | StrOutputParser()
    try:
        q = llm_module.strip_think(chain.invoke({"history": history_msgs, "question": question}))
        q = q.strip().strip('"').strip()
        return q if 0 < len(q) <= 300 else question
    except Exception:
        return question


def _retrieve_with_memory(project: Project, question: str, recent_turns: list[Chat]):
    """Return (RetrievalResult, history_messages). Reformulates the query only when there is
    prior conversation to lean on; otherwise behaves exactly like single-shot retrieval."""
    history_msgs = history_messages(recent_turns)
    search_query = _reformulate(history_msgs, question)
    return retrieve(project, search_query), history_msgs


def validate_ask(project: Project, question: str) -> None:
    """Guard conditions that should fail as a normal HTTP error (before any streaming)."""
    if project.status != ProjectStatus.READY:
        raise ApiError(
            f"Project is not ready for questions yet (status: {project.status}).", 409
        )
    if not question:
        raise ApiError("A question is required.", 400)
    if len(question) > _MAX_QUESTION_CHARS:
        raise ApiError(f"Question is too long (max {_MAX_QUESTION_CHARS} characters).", 400)


def _citations(result: RetrievalResult) -> list[dict]:
    """Evidence behind the answer — file, lines, kind, score, and a snippet."""
    return [
        {
            "file_path": it["file_path"],
            "start_line": it["start_line"],
            "end_line": it["end_line"],
            "chunk_type": it["chunk_type"],
            "symbol_name": it["symbol_name"],
            "score": it["score"],
            "snippet": it["snippet"],
        }
        for it in result.items
    ]


def _explanation(result: RetrievalResult) -> str:
    """A short 'why these sources' note (the explainability requirement)."""
    if not result.items:
        base = "No strongly matching code was found"
        return base + (" — answered from the project overview." if result.used_context_card else ".")
    how = "project overview + top code matches" if result.used_context_card else "top code matches"
    return f"Answered from {how} (best similarity {result.max_similarity})."


def _persist(user_id: int, project_id: int, question: str, answer: str, citations: list[dict]) -> Chat:
    chat = Chat(
        user_id=user_id, project_id=project_id,
        question=question, answer=answer, citations=citations,
    )
    db.session.add(chat)
    db.session.commit()
    return chat


def _model_of(message) -> str:
    md = getattr(message, "response_metadata", None) or {}
    return md.get("model_name") or md.get("model") or "?"


def answer(user, project: Project, question: str) -> dict:
    """Blocking answer (JSON)."""
    recent = _recent_turns(user.id, project.id)
    result, history_msgs = _retrieve_with_memory(project, question, recent)

    chain = ANSWER_PROMPT | llm_module.get_llm()
    message = chain.invoke(
        {"context": format_context(result), "question": question, "history": history_msgs}
    )
    text = llm_module.strip_think(message.content or "")

    citations = _citations(result)
    chat = _persist(user.id, project.id, question, text, citations)
    return {
        "chat_id": chat.id,
        "answer": text,
        "citations": citations,
        "meta": {
            "model": _model_of(message),
            "used_context_card": result.used_context_card,
            "broad": result.broad,
            "max_similarity": result.max_similarity,
            "explanation": _explanation(result),
        },
    }


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def answer_stream(user, project: Project, question: str):
    """Generator of SSE events: meta (with citations) → token* → done (or error)."""
    recent = _recent_turns(user.id, project.id)
    try:
        result, history_msgs = _retrieve_with_memory(project, question, recent)
    except Exception as e:  # e.g. embedding API failure
        yield _sse({"type": "error", "error": f"Retrieval failed: {e}"})
        return

    citations = _citations(result)
    yield _sse(
        {
            "type": "meta",
            "citations": citations,
            "used_context_card": result.used_context_card,
            "max_similarity": result.max_similarity,
            "explanation": _explanation(result),
        }
    )

    chain = ANSWER_PROMPT | llm_module.get_llm()
    think = llm_module.ThinkFilter()
    model = None
    parts: list[str] = []
    try:
        for chunk in chain.stream(
            {"context": format_context(result), "question": question, "history": history_msgs}
        ):
            if model is None:
                model = _model_of(chunk)
                if model == "?":
                    model = None  # keep looking; Groq sets it on a later chunk
            piece = chunk.content or ""
            if piece:
                out = think.feed(piece)
                if out:
                    parts.append(out)
                    yield _sse({"type": "token", "text": out})
        tail = think.flush()
        if tail:
            parts.append(tail)
            yield _sse({"type": "token", "text": tail})
    except ApiError as e:
        yield _sse({"type": "error", "error": e.message})
        return
    except Exception as e:
        yield _sse({"type": "error", "error": f"Generation failed: {e}"})
        return

    chat = _persist(user.id, project.id, question, "".join(parts), citations)
    yield _sse({"type": "done", "chat_id": chat.id, "model": model or "?"})
