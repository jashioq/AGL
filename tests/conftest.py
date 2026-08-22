"""`tests/` on `sys.path`, and the one guard that cannot live in the module it protects.

pytest's prepend import mode inserts, for every file it imports, that file's *basedir* - the first
ancestor directory that is not itself a package - at the front of `sys.path`, and it does so before
importing the file. `tests/` holds no `__init__.py`, so this conftest's basedir is `tests/`, and
conftest files are imported before collection starts. That is the whole of what makes `from
contracts.store import StoreContract` resolve from any test module under `tests/`, whichever
directory pytest was invoked from and whether it was invoked on the whole suite or on one file - and
it is also what lets the import below reach `instruments.loopback` at all.

**This file used to say its emptiness was the design, and the reason it gave still holds.** A
fixture a contract suite needs is that suite's own, declared on the class an implementer subclasses,
so that pointing a suite at an implementation is one visible override and never a hunt through
conftest files for what else the suite quietly reads. Nothing below weakens that rule, because
nothing below is a fixture a suite *reads*: it is a fixture no suite can decline, and the two are
opposites. A guard that protects by default is exactly the thing that cannot be declared in the
module it protects. A module-scoped autouse fixture guards the file it is written in and no other,
so the next test file added inherits it only if somebody remembers - and "somebody remembers" is the
mechanism this file exists to replace. Stage 7.1 wrote that fixture in
`tests/adapters/test_claude_code_runner.py`; stage 8 adds a second adapter test file, and the Codex
CLI has the identical dangerous shape - subscription auth plus a redirectable endpoint.

**What is being guarded against, measured rather than argued.** Point `ANTHROPIC_BASE_URL` at a
socket and leave `ANTHROPIC_API_KEY` unset, and the `claude` CLI falls back to the operator's own
subscription credential: it sends `Authorization: Bearer sk-ant-…`, a live token, to whatever is
listening on that port. Any non-empty dummy makes it send `x-api-key: <dummy>` and nothing else. So
both variables below are load-bearing and neither is belt-and-braces. The redirect is an *override*
and not a default, which is the part worth knowing: on the machine this was written on
`ANTHROPIC_BASE_URL` was already set in the ambient shell, to `https://api.anthropic.com`. A suite
that inherited its environment would have reached the paid endpoint on the first CLI it spawned.

**Codex is covered by taking the credential away rather than by redirecting the endpoint**, which is
the stronger of the two: there is nothing left to leak, rather than a leak into a socket we own.
`codex` 0.149.0 reads both its configuration and its `auth.json` out of `$CODEX_HOME`, established
with free instruments only - `codex login status` says "Logged in using ChatGPT" against the
operator's own `~/.codex` and "Not logged in" against an empty directory, and a deliberately broken
`$CODEX_HOME/config.toml` makes the CLI refuse to start while naming that exact path. So the
temporary directory below puts this machine's ChatGPT OAuth tokens - a real `access_token` and
`refresh_token`, `auth_mode: "chatgpt"`, `OPENAI_API_KEY: null` - outside the reach of any process a
test starts.

**What this does not cover, said plainly so that nobody reads it as more.** There is no base-URL
redirect for Codex here. `codex --help` documents no endpoint environment variable; the endpoint is
configuration (`chatgpt_base_url`, `openai_base_url`, `model_providers.<id>.base_url`), and proving
that redirecting any of them actually diverts a request costs a `codex exec`, which is a paid turn.
A named variable that turned out to be the wrong one would be worse than none, because the fixture
would then read as protection it was not providing. That measurement belongs to deliverable 8.0, the
Codex capability findings, and `scripts/check`'s paid-endpoint gate repeats the caveat where a
reader will meet it. Until then, Codex is protected by having no credential and not by where it
would send one.
"""

from collections.abc import Iterator

import pytest

from instruments.loopback import DUMMY_KEY, REPLY, Loopback


@pytest.fixture(scope="session", autouse=True)
def loopback(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Loopback]:
    """Every test in this repository, pointed away from anything that could charge for an answer.

    Session-scoped and autouse: the whole point is that a test file written next week is covered by
    a fixture nobody remembered to ask for. One listener for a whole run rather than one per module,
    because a second listener is not a second layer of protection - it is a second address, and a
    CLI pointed at one while a test reads the other is the failure
    `test_no_test_in_this_module_can_reach_a_paid_endpoint` asserts against by comparing the two.

    Three environment variables, and each is doing separate work:

      * `ANTHROPIC_BASE_URL` sends `claude` at `instruments.loopback`, which opens no outbound
        socket and forwards nothing anywhere - so "free" is a property of the process on the far
        side, not a promise made test by test.
      * `ANTHROPIC_API_KEY` keeps the operator's OAuth bearer token off that socket. Unset, the CLI
        reaches for the subscription credential instead; the value is irrelevant and non-empty is
        the whole requirement. Anyone deleting this line is handing a live token to a local port.
      * `CODEX_HOME` points the Codex CLI at an empty directory, so the ChatGPT tokens in the
        operator's own `~/.codex/auth.json` are not reachable by anything a test spawns. It does
        **not** redirect Codex's endpoint - see this module's docstring for why that is deliberate.

    Hand-rolled around `pytest.MonkeyPatch.context()` because `monkeypatch` is function-scoped and
    cannot be asked for at session scope. The context restores the environment on the way out, which
    matters for `CODEX_HOME` in particular: leaving it set would point a later process at a
    directory pytest has since deleted.
    """
    with Loopback() as endpoint, pytest.MonkeyPatch.context() as environment:
        environment.setenv("ANTHROPIC_BASE_URL", endpoint.url)
        environment.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
        environment.setenv("CODEX_HOME", str(tmp_path_factory.mktemp("codex-home-no-credential")))
        yield endpoint


@pytest.fixture(autouse=True)
def _one_test_at_a_time(loopback: Loopback) -> Iterator[None]:
    """One test's traffic is never another's, and no test leaves a live credential behind it.

    Both halves used to live in `tests/adapters/test_claude_code_runner.py` and both had to move,
    for different reasons.

    The teardown is the credential-leak measurement, and it is the half the stage asked to be made
    repo-wide: every request every test caused is checked for an `Authorization` header, which is
    what the CLI sends when it falls back to the operator's own subscription credential, and which
    therefore appears the moment the dummy key stops being set - whatever anyone believed about it.
    The value is never read: `instruments.loopback` redacts it on the way in, and the assertion is
    only about the header being there at all. Scoped to one module it measured one module; the
    thing worth knowing is that *no* test in the repository sent one.

    The reset had to move with it. It reads as module-local bookkeeping - and it was, while the
    listener was module-scoped - but the listener is a session-wide instrument now, so "one test's
    traffic is never another's" stopped being a fact about one file. Leaving the clear behind would
    have two costs: `composed()` would read whichever run happened to go first across the whole
    suite, and this teardown would blame a test for a header some earlier test's process sent.
    """
    loopback.clear()
    loopback.says = REPLY
    yield
    bearer = [
        seen.path
        for seen in loopback.requests
        if any(name.lower() == "authorization" for name in seen.headers)
    ]
    assert not bearer, (
        f"a CLI this test started sent an Authorization header to {bearer}. That is the operator's "
        f"own OAuth bearer token: the CLI falls back to it whenever ANTHROPIC_API_KEY is unset or "
        f"empty, and with the base URL redirected it goes to whatever is listening on the port. It "
        f"landed on this suite's own loopback, which redacts it - but the next reader to point "
        f"that variable somewhere else would be shipping a live credential"
    )
