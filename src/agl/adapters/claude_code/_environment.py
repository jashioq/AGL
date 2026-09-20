from collections.abc import Mapping
from typing import Final

__all__ = ["withheld"]

# Every name the CLI reads to configure itself begins with one of these two words: 694 distinct ones
# in the 2.1.277 bundle, and a release adds more. So the namespace is what AGL answers for, rather
# than a list of names to refuse - one of those goes stale on the next release while still reading
# like a guard.
_VENDOR_PREFIXES: Final = ("CLAUDE", "ANTHROPIC")

# The three `subprocess_cli.connect` writes around the mapping below - it sets two and drops
# `CLAUDECODE` from what it inherits. `CLAUDE_CODE_ENTRYPOINT` is the one that bites: it is written
# *before* the merge, so blanking it here replaces the SDK's own `sdk-py` with nothing.
_WRITTEN_BY_THE_SDK: Final[frozenset[str]] = frozenset(
    {"CLAUDECODE", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_CODE_ENTRYPOINT"}
)

# The allowlist. A name is here because withholding it stops this machine reaching its endpoint at
# all, or sends a credential somewhere AGL did not choose. Everything else in the namespace is a
# preference or a capability, and those are AGL's to decide rather than the shell's.
_ALLOWED: Final[frozenset[str]] = frozenset(
    {
        # `tests/conftest.py` points this at a loopback for every test in the repository and
        # `check_ready` starts a real CLI on every `scripts/check`, so a session that does not carry
        # it is a session against the paid endpoint.
        "ANTHROPIC_BASE_URL",
        # Not a credential to withhold but a credential to choose: empty or absent, the CLI reaches
        # for the operator's own OAuth bearer token instead, which is why `tests/conftest.py`
        # exports a dummy rather than nothing.
        "ANTHROPIC_API_KEY",
        # The bearer an operator behind a gateway authenticates with, and its only spelling.
        "ANTHROPIC_AUTH_TOKEN",
        # The headless login. The bundle's own advice for a mismatched account is to unset this,
        # which is what says it is read.
        "CLAUDE_CODE_OAUTH_TOKEN",
        # The config home, and the one name here where a blank is worse than the operator's value:
        # the bundle resolves `CLAUDE_CONFIG_DIR ?? <home>/.claude`, and `??` passes an empty string
        # through, so a blank would name the empty path rather than fall back to the default.
        "CLAUDE_CONFIG_DIR",
        # Where the vendor's own SDK half reads `credentials/<account>.json`.
        "ANTHROPIC_CONFIG_DIR",
        # mTLS to a corporate endpoint. The bundle holds these three in one set with
        # `NODE_EXTRA_CA_CERTS` and `NODE_TLS_REJECT_UNAUTHORIZED`, which are outside the namespace
        # and travel untouched, so withholding these would break up a set the vendor treats as one.
        "CLAUDE_CODE_CLIENT_CERT",
        "CLAUDE_CODE_CLIENT_KEY",
        "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
        # Which trust stores are read, `bundled` and `system` in a comma-separated list. A machine
        # behind an intercepting proxy needs its own and reaches nothing without it.
        "CLAUDE_CODE_CERT_STORE",
        # Read only after `HTTP_PROXY` and `HTTPS_PROXY`, which are outside the namespace and travel
        # untouched. Withholding the prefixed spelling alone would make AGL's answer depend on which
        # of two spellings an operator happened to use.
        "CLAUDE_CODE_HTTP_PROXY",
        "CLAUDE_CODE_HTTPS_PROXY",
    }
)

def withheld(parent: Mapping[str, str]) -> dict[str, str]:
    """Every vendor name this environment carries that AGL will not pass on, mapped to the blank."""
    # Blanked rather than dropped: `subprocess_cli` merges this over what it inherited and has no
    # value meaning "as if it had never been exported". The empty string is what 2.1.277 reads as
    # nothing on each hazard measured - `CLAUDE_CODE_RESTRICTED`, `ANTHROPIC_DEFAULT_OPUS_MODEL` and
    # `CLAUDE_CODE_EFFORT_LEVEL` all behave as they do with the name unset.
    return {name: "" for name in parent if _blanked(name)}

def _blanked(name: str) -> bool:
    return (
        name.startswith(_VENDOR_PREFIXES)
        and name not in _ALLOWED
        and name not in _WRITTEN_BY_THE_SDK
    )
