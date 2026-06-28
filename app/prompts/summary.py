from __future__ import annotations

from app.types import ConversationMessage


def build_summary_prompt_messages(
    existing_summary: str,
    messages: list[ConversationMessage],
) -> list[dict[str, str]]:
    transcript = "\n".join(f"{message.role}: {message.content}" for message in messages)
    return [
        {
            "role": "system",
            "content": (
                "Summarize the conversation for future turns. Preserve user goals, "
                "open questions, factual commitments, and unresolved tasks. "
                "Return plain text in 6 sentences or fewer."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Existing summary:\n{existing_summary or '(none)'}\n\n"
                f"Conversation excerpt:\n{transcript}"
            ),
        },
    ]
