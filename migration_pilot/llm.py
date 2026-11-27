"""Works with Azure OpenAI, OpenAI, or a scripted fake model in tests."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Protocol


class ChatModel(Protocol):
    def __call__(self, system: str, user: str) -> str: ...


def get_chat_model() -> ChatModel | None:
    """Return a model from environment variables, or None if no key is set (rules mode)."""
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        from langchain_openai import AzureChatOpenAI

        client = AzureChatOpenAI(
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            temperature=0,
        )
    elif os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        client = ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    else:
        return None

    def call(system: str, user: str) -> str:
        return client.invoke([("system", system), ("user", user)]).content

    return call


def scripted_model(responses: list[str]) -> Callable[[str, str], str]:
    """A fake model that returns canned responses in order."""
    queue = list(responses)

    def call(system: str, user: str) -> str:
        if not queue:
            raise AssertionError("Scripted model ran out of responses.")
        return queue.pop(0)

    return call
