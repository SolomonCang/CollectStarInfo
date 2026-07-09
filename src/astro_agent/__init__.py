"""Astronomy target info search agent."""

__all__ = ["TargetInfoAgent"]


def __getattr__(name: str):
    if name == "TargetInfoAgent":
        from .agent import TargetInfoAgent

        return TargetInfoAgent
    raise AttributeError(f"module 'astro_agent' has no attribute {name!r}")
