"""Public text adapter interface; independent of audio and browser transport."""
from typing import NotRequired, Protocol, TypedDict


class TextMessage(TypedDict):
    key: str
    turn: str
    text: str


class Reply(TextMessage):
    streaming: bool


class TextSnapshot(TypedDict):
    session: str
    url: str
    busy: bool
    users: list[TextMessage]
    reply: Reply | None
    userKey: str
    error: str
    editor: int
    draft: bool
    sendButtons: int
    activeTurn: str


class SendResult(TypedDict):
    accepted: bool
    uncertain: bool
    user_key: NotRequired[str]
    turn: NotRequired[str]


class TextAdapter(Protocol):
    """A connection is pinned to one conversation until closed.

    connect() returns an initial snapshot; callers skip its existing messages.
    snapshot() returns visible user text and the newest assistant response.
    busy=True or reply.streaming=True prohibits treating a reply as final.
    send() refuses nonempty drafts and performs at most one submission; an
    uncertain result or an exception must never be retried automatically.
    Closing a connection does not close the user's browser or conversation.
    """
    session: str

    def connect(self) -> TextSnapshot: ...
    def snapshot(self) -> TextSnapshot: ...
    def send(self, text: str) -> SendResult: ...
    def close(self) -> None: ...
