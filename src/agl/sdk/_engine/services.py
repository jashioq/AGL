
from dataclasses import dataclass

from agl.ports.agent import AgentRunner
from agl.ports.clock import Clock
from agl.ports.history import History
from agl.ports.integration import Integrator
from agl.ports.store import Store
from agl.ports.terminal import Terminal
from agl.ports.verifier import Verifier
from agl.ports.workspace import WorkspaceProvider

__all__ = ["Services"]


@dataclass(frozen=True, slots=True)
class Services:

    store: Store

    workspaces: WorkspaceProvider

    history: History

    integrator: Integrator

    verifier: Verifier

    terminal: Terminal

    clock: Clock

    agents: AgentRunner

    build: str
