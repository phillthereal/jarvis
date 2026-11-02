from dataclasses import dataclass
from typing import Protocol


@dataclass
class Answer:
    text: str
    provider: str
    model: str
    ok: bool
    error: str | None
    latency_ms: int


class Provider(Protocol):
    def complete(self, prompt: str, system: str | None = None, timeout: float = 60) -> Answer: ...
