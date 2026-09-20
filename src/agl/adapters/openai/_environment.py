from collections.abc import Mapping
from typing import Final

__all__ = ["composed"]

# Every name the harness reads to configure itself begins with one of these two words, and
# `--ignore-user-config` reaches none of them: it isolates `config.toml` completely and the
# environment not at all, which its own help says of authentication in particular - "auth still
# uses CODEX_HOME".
_VENDOR_PREFIXES: Final = ("CODEX", "OPENAI")

# The allowlist. A name is here because withholding it stops this machine reaching its endpoint at
# all, or sends a credential somewhere AGL did not choose. Everything else in the namespace is a
# preference or a capability, and those are AGL's to decide rather than the shell's.
_ALLOWED: Final[frozenset[str]] = frozenset(
    {
        # Configuration *and* credentials, and `tests/conftest.py` points it at a directory holding
        # neither for every test in the repository - so a run that does not carry it is a run
        # against the operator's own credential store.
        "CODEX_HOME",
        # The three credential variables the binary names in one sentence beside `auth.json`, when
        # it says no credentials were found. Withholding one does not remove a credential, it picks
        # a different one, and the one left is the operator's ChatGPT login.
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
        "OPENAI_API_KEY",
        # `tests/conftest.py` records that nobody has established which variable, if any, moves this
        # harness off its endpoint, and why the measurement costs a paid turn. Withholding this one
        # would be answering that question by accident.
        "OPENAI_BASE_URL",
        # Trust, read beside `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` and
        # `NODE_EXTRA_CA_CERTS`, which are outside the namespace and travel untouched - so
        # withholding it would break up a set the vendor treats as one.
        "CODEX_CA_CERTIFICATE",
    }
)

def composed(parent: Mapping[str, str], chosen: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's whole environment: this one less what AGL withholds, plus what AGL set."""
    # Dropped rather than blanked, which is the one thing this adapter can do and the Claude one
    # cannot: `create_subprocess_exec` is handed the environment outright, so a name left out of
    # this mapping is a name the child does not have. Nothing outside the namespace is touched, so
    # `PATH`, `HOME`, `TMPDIR` and whatever the repository's own build reads travel as they are.
    kept = {name: value for name, value in parent.items() if not _withheld(name)}
    return kept if chosen is None else {**kept, **chosen}

def _withheld(name: str) -> bool:
    return name.startswith(_VENDOR_PREFIXES) and name not in _ALLOWED
