"""Chat turn — one question and its answer, with citations for explainability."""

from sqlalchemy.dialects.postgresql import JSONB

from ..extensions import db


class Chat(db.Model):
    __tablename__ = "chats"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )

    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text)
    # Evidence behind the answer (HLD-v2 §5): list of
    #   {file_path, start_line, end_line, score, snippet}
    citations = db.Column(JSONB)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)

    project = db.relationship("Project", back_populates="chats")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "citations": self.citations or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Chat {self.id} project={self.project_id}>"
