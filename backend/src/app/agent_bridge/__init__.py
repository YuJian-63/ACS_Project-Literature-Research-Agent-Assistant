"""Isolated Agent v1 execution boundary."""

from .subprocess_client import AgentProcessError, run_agent

__all__ = ["AgentProcessError", "run_agent"]
