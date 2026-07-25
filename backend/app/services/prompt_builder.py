"""Prompt construction (HLD-v2 §2/§5).

Exposes an LCEL `ChatPromptTemplate` (`ANSWER_PROMPT`) plus helpers that turn a
`RetrievalResult` into the `{context}` string and prior turns into history messages. The system
prompt constrains the model to the provided context and forbids inventing files/paths, which is
our guardrail against hallucination.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from .retrieval_service import RetrievalResult

_SYSTEM = (
    "You are a senior engineer helping a developer understand an unfamiliar codebase. You are "
    "given excerpts retrieved from the project (and sometimes a structural overview). Answer the "
    "developer's question using ONLY that provided material.\n"
    "\n"
    "GROUNDING — this overrides everything else:\n"
    "- Base every statement on the provided context. Never invent files, paths, functions, APIs, "
    "libraries, config, or behavior.\n"
    "- Do NOT fill gaps with how such projects 'typically' or 'usually' work, with framework "
    "conventions, or with what the project 'probably' does. If it is not in the context, you do "
    "not know it.\n"
    "- If the context answers only part of the question, answer that part and briefly state that "
    "the rest is not shown in the retrieved code. Do not guess the missing part.\n"
    "- If the context does not contain the answer at all, reply with exactly this sentence and "
    "nothing else: \"The information was not found in this project.\"\n"
    "\n"
    "ANSWERING STYLE:\n"
    "- Explain in clear prose: HOW it works, the overall flow, and the WHY, so the reader "
    "understands without reading the code. Be concise; short headings or bullets for a flow are "
    "fine.\n"
    "- Do NOT paste code or walk through it line by line, UNLESS the user explicitly asks for a "
    "specific function's implementation — only then include that code.\n"
    "- You may name a function or concept when it aids understanding, but do NOT include any "
    "'Key Files' / 'Components' / 'Structure' list or per-file breakdown, and do NOT put file "
    "paths anywhere in the body.\n"
    "\n"
    "ENDING:\n"
    "- If you answered from specific file(s), end with ONE final line listing only the real paths "
    "from the context that your answer actually used: `Implemented in <relative/path>` (comma-"
    "separate if several). This is the only place a file path may appear.\n"
    "- If you replied that the information was not found, do NOT output this line at all."
)

# {history} replays recent turns (empty for a first question); {context} carries the retrieved
# code (and the structural overview, when retrieval was weak/broad) — the model's only source.
ANSWER_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM),
        MessagesPlaceholder("history"),
        (
            "human",
            "Below is the ONLY source material for your answer — retrieved from the project.\n\n"
            "{context}\n\n## Question\n{question}",
        ),
    ]
)

_MAX_TREE = 120            # cap file-tree lines in the overview
_MAX_SIGNATURE_FILES = 40  # cap files listed in the signature map for broad questions
_CHUNK_PROMPT_CHARS = 2500  # cap per-chunk code sent to the LLM (bounds prompt tokens)
_HISTORY_ANSWER_CHARS = 800  # truncate replayed prior answers to bound prompt tokens


def _format_context_card(card: dict) -> str:
    lines = ["## Project overview"]
    if card.get("frameworks"):
        lines.append("Frameworks/build: " + ", ".join(card["frameworks"]))
    if card.get("languages"):
        langs = ", ".join(f"{k} ({v})" for k, v in card["languages"].items())
        lines.append("Languages: " + langs)
    if card.get("entrypoints"):
        lines.append("Entrypoints: " + ", ".join(card["entrypoints"]))
    if card.get("readme_excerpt"):
        lines.append("\nREADME excerpt:\n" + card["readme_excerpt"])
    tree = card.get("file_tree") or []
    if tree:
        lines.append("\nFile tree:\n" + "\n".join(tree[:_MAX_TREE]))
    return "\n".join(lines)


def _format_signatures(repo_map: dict) -> str:
    signatures = (repo_map or {}).get("signatures") or {}
    lines = ["## Code map (file → definitions)"]
    for path in list(signatures.keys())[:_MAX_SIGNATURE_FILES]:
        names = ", ".join(
            f"{s['type']}:{s['name']}" for s in signatures[path] if s.get("name")
        )
        if names:
            lines.append(f"{path}: {names}")
    return "\n".join(lines)


def _format_chunks(items: list[dict]) -> str:
    if not items:
        return "## Relevant code\n(No strongly matching code snippets were found.)"
    blocks = ["## Relevant code snippets"]
    for it in items:
        header = f"File: {it['file_path']} (lines {it['start_line']}-{it['end_line']})"
        content = it["content"]
        if len(content) > _CHUNK_PROMPT_CHARS:
            content = content[:_CHUNK_PROMPT_CHARS] + "\n… (truncated)"
        blocks.append(f"{header}\n```\n{content}\n```")
    return "\n\n".join(blocks)


def format_context(result: RetrievalResult) -> str:
    """Build the `{context}` string: structural overview (when attached) + retrieved chunks."""
    parts: list[str] = []
    if result.used_context_card and result.context_card:
        parts.append(_format_context_card(result.context_card))
    if result.broad and result.repo_map:
        parts.append(_format_signatures(result.repo_map))
    parts.append(_format_chunks(result.items))
    return "\n\n".join(parts)


def history_messages(history) -> list[BaseMessage]:
    """Replay recent turns as alternating Human/AI messages (prior answers truncated)."""
    messages: list[BaseMessage] = []
    for turn in history or []:
        messages.append(HumanMessage(turn.question))
        if turn.answer:
            messages.append(AIMessage(turn.answer[:_HISTORY_ANSWER_CHARS]))
    return messages
