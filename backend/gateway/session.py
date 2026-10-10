"""Une session = une conversation de l'agent, identifiée par son trace_id."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class Session:
    agent_id: str
    user_id: str | None = None
    trace_id: UUID = field(default_factory=uuid4)
    run_id: UUID | None = None
    last_event: UUID | None = None  # cause du prochain événement
    closed: bool = False
    diverted: bool = False  # posée par la couche de leurres, jamais retirée
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
