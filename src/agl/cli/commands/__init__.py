
from collections.abc import Callable

from agl.ports.ids import ProjectName
from agl.sdk._engine.services import Services

__all__ = ["Registered"]


type Registered = Callable[[], tuple[ProjectName, Services]]
