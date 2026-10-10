"""Passerelle de traçage entre l'agent victime et tout ce qu'il touche."""

from gateway.proxy import Gateway, GatewayError, ToolFailed, TraceUnavailable, UnknownSession, UnknownTool
from gateway.session import Session

__all__ = [
    "Gateway",
    "GatewayError",
    "Session",
    "ToolFailed",
    "TraceUnavailable",
    "UnknownSession",
    "UnknownTool",
]
