from agl.sdk import Row, Rows, Run, Screen

__all__ = ["board"]

def board(run: Run, request: str) -> Screen:
    return Screen(Rows([Row("request", request), Row("agent", run.activity or "")]))
