"""Research-only multi-agent scaffold for crypto alpha work."""

from .models import ALPHA_AGENT_VERSION
from .orchestrator import AlphaAgentOrchestrator
from .roles import default_registry

__all__ = ["ALPHA_AGENT_VERSION", "AlphaAgentOrchestrator", "default_registry"]
