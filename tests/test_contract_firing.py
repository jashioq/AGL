"""Structural test: every contract in `.importlinter` refuses the violation it was written to
refuse. Six contracts, and before this file nothing in this suite had watched one of them say no.

`tests/test_contract_listings.py` next door checks that the hand-maintained *listings* inside three
of the contracts still agree with the tree they police. That is a weaker and different claim: a
listing can be perfect and the rule still enforce nothing, if the contract is aimed at a package
that no longer exists, if an `ignore_imports` expression quietly swallows the whole source side, or
if a later edit turns a `forbidden` contract into one whose `source_modules` and `forbidden_modules`
overlap - import-linter skips overlapping pairs in silence, which is exactly how contract 2 comes to
have no opinion about `agl.ports` itself. **A contract nobody has seen break is a contract nobody
has seen work.** Four of the six were once found failing open by inspection; this file is what
would have found them by measurement.

So each probe below fabricates the import that contract exists to catch, and asserts that *that*
contract, named by its stable number, goes from kept to broken. Both halves matter. "Something
broke" is satisfied by a fabrication a different contract caught - `agl.workflows -> agl.config`
breaks contract 1 as well as contract 6, and a probe of 6 that only asked for a failure would pass
on contract 1's verdict forever, including after somebody deleted contract 6. And "it broke" alone
is satisfied by a contract that is broken already, so every probe asserts the same contract is
*kept* on the unmodified graph in the same breath.

## What each probe records, and why it is the whole set rather than one name

`breaks` is every contract the fabrication breaks, not only the one the probe is of. Writing it out
is what makes the overlaps visible instead of incidental, and two of them are real facts about this
configuration rather than accidents of the fabrication:

  * contract 6 is *wholly* implied - its config half by contract 1, which puts `agl.workflows`
    below `agl.config`, and its adapters half by contract 5, whose `agl.*` source includes
    `agl.workflows`. Both probes of it break a second contract, and neither can be written not to.
    `.importlinter`'s comment on contract 6 says the restatement is for the sake of the message a
    workflow author reads; these two rows are where that claim is measured rather than asserted.
  * every other probe breaks exactly one contract, which is a stronger result than it looks. It
    means each of the other five is load-bearing on its own: delete it and a fabrication that is
    caught today is caught by nothing.

## Why a fabricated import and not a fabricated file

The obvious mechanism is to write a violating module into `src/agl/`, run `lint-imports`, and read
the exit status. It works and it is what an operator does; it is also a subprocess and a full graph
build per probe, it edits the repository the suite is running out of, and a probe that crashed
between writing and deleting would leave a broken tree behind. `grimp` builds one graph in about
eight milliseconds here (measured, on a cold cache, `include_external_packages=True` and all), and
import-linter's contract objects take that graph directly - `contract.check(graph, verbose=False)`
is the same call `lint-imports` makes, from the same classes, over options parsed out of the same
`.importlinter`. Nothing about the rules is restated here: the numbers, the types, the module lists
and the ignore expressions are all read from the file under test.

**Every check gets its own copy of the graph, and that is a requirement rather than tidiness.**
`Contract.check`'s own docstring says the graph "may be mutated without affecting other contracts",
and both `forbidden` and `layers` do mutate it - `remove_ignored_imports` deletes the ignored edges
from the graph it is handed. import-linter's own runner deep-copies per contract for that reason.
So does the helper below, and the pristine graph is never handed to anything: probe order cannot
become load-bearing, and a probe cannot leave a fabrication behind for the next one to trip over.

The graph is built once per module because there is no reason to build it nine times, not because
building it is slow. What that buys is not speed but sameness: every verdict in this file is taken
over one reading of `src/agl/`, so a probe that disagrees with its neighbour disagrees about the
rule and not about the tree.

## A fabrication that fabricates nothing is the failure mode to design against

`graph.add_import` invents any module name it has not seen - `add_import(importer="agl.ports.idz",
imported="agl.api")` succeeds, silently, and the resulting probe measures a rule against a module
that does not exist. A typo would therefore not fail; it would pass, on a contract that was never
consulted about anything real. So every import probe asserts both endpoints are already in the
graph before fabricating anything, and the module probe asserts the opposite - that the name it is
about to add is one the tree does not already hold.

## Long to scroll, inside the ceiling, and the split that would pay is not available

A hundred lines of it are the `PROBES` table and another eighty are this docstring, and a probe is
a fabrication plus the reason the fabrication is the right shape - the reason being the part a
later reader needs and the part no mechanism can hold. Splitting the table off from the machinery
that runs it would put the argument for a row one file away from the assertion that prints it, and
buy nothing: what is left is two fixtures, one loop and the failure messages. This file stood over
the ceiling while the gate counted every line; the gate counts code now, and 243 of these 473 lines
are code, so the warning that prompted this section no longer fires. The section stays because the
question it answers - why is the table not its own module - is asked by the file's shape, not by
the gate.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import grimp
import pytest
from importlinter import Contract
from importlinter.api import read_configuration
from importlinter.contracts.forbidden import ForbiddenContract
from importlinter.contracts.independence import IndependenceContract
from importlinter.contracts.layers import LayersContract

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
CONFIG_FILE: Final = REPO_ROOT / ".importlinter"

# The contract *types* AGL uses, and the classes import-linter checks them with. Not a registry
# lookup: `importlinter.api.read_configuration` is the documented way in and it stops at the parsed
# options, so the three classes are named here instead. A seventh contract of a fourth type fails
# below with a message saying so rather than being quietly skipped.
CONTRACT_CLASSES: Final[Mapping[str, type[Contract]]] = {
    "layers": LayersContract,
    "forbidden": ForbiddenContract,
    "independence": IndependenceContract,
}

# Contract numbers are stable - `.importlinter`'s header says so, and failure reports cite them by
# number - and the type is half of what a number means: contract 4 becoming a `forbidden` contract
# would leave every probe below still running and no longer probing what it says it does. This is
# where all six numbers are pinned, `tests/test_contract_listings.py` having handed over the four
# it used to pin when it stopped reading contract 1.
CONTRACT_TYPES: Final[Mapping[str, str]] = {
    "1": "layers",
    "2": "forbidden",
    "3": "forbidden",
    "4": "independence",
    "5": "forbidden",
    "6": "forbidden",
}

# A top-level name `src/agl/` does not hold, for the exhaustiveness probe. Deliberately not the name
# of anything the tree could plausibly grow.
UNDECLARED_MEMBER: Final = "agl.probe_that_no_layer_declares"


@dataclass(frozen=True)
class Probe:
    """One import that does not exist, and what happens to the six contracts when it does.

    `contract` is the number this probe is *of* - the contract whose failure is the point. `breaks`
    is every number that goes broken, which includes `contract` and is asserted as a set, so a
    fabrication that grows a second victim is a change somebody has to come here and write down.
    `rule` is the sentence the fabrication violates, and it is what the failure message prints:
    a reader who has never opened `.importlinter` should be able to tell from the output what was
    supposed to happen.
    """

    contract: str
    importer: str
    imported: str
    rule: str
    breaks: frozenset[str]

    def __post_init__(self) -> None:
        assert self.contract in self.breaks, (
            f"probe of contract {self.contract} does not list it in `breaks`, so it is a probe of "
            f"whatever else it happens to break"
        )

    @property
    def shown(self) -> str:
        return f"{self.importer} -> {self.imported}"


PROBES: Final[tuple[Probe, ...]] = (
    # Contract 1 makes three separable claims and two of them are probed here: ordering once, and
    # independence twice - one row per `|` pair, because a pair respelled `:` is invisible to the
    # other pair's row. The exhaustiveness claim is a test of its own further down. The ordering
    # half first: `adapters` is Ring 2 and `api` is Ring 3, so this is the dependency rule read
    # backwards.
    Probe(
        contract="1",
        importer="agl.adapters.system_clock",
        imported="agl.api",
        rule="an adapter reaching up to agl.api - the layer stack read backwards",
        breaks=frozenset({"1"}),
    ),
    # The independence half, first pair. `agl.cli | agl.testing` is the spelling that says these
    # two are one level and may not import each other, and independence is the half of contract 1 a
    # rewrite is most likely to lose - the `containers` rewrite was checked against exactly this
    # row.
    Probe(
        contract="1",
        importer="agl.cli.commands.run",
        imported="agl.testing",
        rule="the CLI importing the harness - independent siblings, which `|` is what says",
        breaks=frozenset({"1"}),
    ),
    # The independence half, second pair - `agl.sdk | agl.adapters`, which is `ARCHITECTURE.md`'s
    # "The dependency rule": "siblings and may not import each other". Contract 1 once had three
    # probes and this was not one of them: the row above was the only independence probe there was,
    # so this pair was enforced by nothing that anything checked. Respelling it `:` left
    # `lint-imports` at six kept, zero broken, and the whole suite green - which is this file's own
    # thesis arriving one row short.
    #
    # **The direction is forced, and a probe the other way round would pass for the wrong reason.**
    # Contract 5 forbids `agl.* -> agl.adapters` and so already catches `sdk -> adapters` on its
    # own - measured: that fabrication breaks 1, 5 and 6, and still breaks 5 and 6 with this pair
    # spelled `:`, so a probe of it would report a failure whether or not contract 1 had an opinion.
    # `adapters -> sdk` is the direction nothing else covers, and it discriminates exactly: contract
    # 1 alone on the file as it stands, and nothing at all under the `:` mutation.
    Probe(
        contract="1",
        importer="agl.adapters.git.history",
        imported="agl.sdk.errors",
        rule="an adapter importing the SDK - siblings over ports, which `|` is what says",
        breaks=frozenset({"1"}),
    ),
    # Contract 2's inner ring: `ids` is a pure type an ABC speaks, `store` is an ABC that speaks
    # one, and the arrow may only run the other way.
    Probe(
        contract="2",
        importer="agl.ports.ids",
        imported="agl.ports.store",
        rule="a pure type importing the ABC that speaks it",
        breaks=frozenset({"2"}),
    ),
    # Contract 3 confines each vendor SDK to *its own* adapter, which is a stronger claim than
    # "adapters may import vendors" - so the fabrication is the wrong adapter, not a random module.
    # The rich terminal reaching for the Claude SDK is the exact failure the contract exists to
    # stop: an `agl[terminal]` install dragging in `agl[claude]`.
    Probe(
        contract="3",
        importer="agl.adapters.rich_terminal.terminal",
        imported="claude_agent_sdk",
        rule="one vendor's adapter importing the other vendor's SDK",
        breaks=frozenset({"3"}),
    ),
    # Contract 4: two adapters that stand behind different ports, one naming the other. Contract 5
    # cannot see this - it skips the (agl.adapters, agl.adapters) pair as self-overlapping - which
    # is the whole reason contract 4 exists, and the single-element `breaks` is that in evidence.
    Probe(
        contract="4",
        importer="agl.adapters.git.workspace",
        imported="agl.adapters.shell.verifier",
        rule="one adapter importing another, neither of them agl.adapters.routing",
        breaks=frozenset({"4"}),
    ),
    # Contract 5: `agl.api` is above `agl.adapters` in the stack, so contract 1 has no objection -
    # the objection is that a module which is not the composition root said the name of an adapter.
    Probe(
        contract="5",
        importer="agl.api",
        imported="agl.adapters.git.history",
        rule="a module other than agl.config.container naming an adapter",
        breaks=frozenset({"5"}),
    ),
    # Contract 6, adapters half. Contract 5 catches it too, because `agl.*` includes `agl.workflows`
    # - the point of the restatement is the sentence the failure prints, not extra coverage.
    Probe(
        contract="6",
        importer="agl.workflows.split.chunks",
        imported="agl.adapters.system_clock",
        rule="a workflow reaching past the SDK to an adapter",
        breaks=frozenset({"5", "6"}),
    ),
    # Contract 6, config half. Contract 1 catches this one, `agl.config` being a layer above
    # `agl.workflows`, and for the same reason.
    Probe(
        contract="6",
        importer="agl.workflows.fix.roles",
        imported="agl.config.schema",
        rule="a workflow reading configuration instead of being handed it",
        breaks=frozenset({"1", "6"}),
    ),
)


# --- Reading the real `.importlinter` and building the real contract objects ---------------------


def _contract_options() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The real config, as `(session options, one options dict per contract)`."""
    parsed = read_configuration(str(CONFIG_FILE))
    session: dict[str, Any] = parsed["session_options"]
    contracts: list[dict[str, Any]] = parsed["contracts_options"]
    assert contracts, (
        f"{CONFIG_FILE} parsed to no contracts at all, so every probe below would be asserting "
        f"about an empty set. Check the path at the top of this file."
    )
    return session, contracts


@pytest.fixture(scope="module")
def contracts() -> Mapping[str, Contract]:
    """Every contract in `.importlinter`, built by import-linter's own classes, keyed by number."""
    session, options = _contract_options()
    built: dict[str, Contract] = {}
    for contract in options:
        number = str(contract["id"])
        kind = str(contract["type"])
        assert kind in CONTRACT_CLASSES, (
            f"contract {number} in {CONFIG_FILE} is a `{kind}` contract, which this file does not "
            f"know how to build. Add its class to CONTRACT_CLASSES and give it a probe - an "
            f"unbuilt contract is one nobody here has watched refuse anything."
        )
        built[number] = CONTRACT_CLASSES[kind](
            name=str(contract["name"]), session_options=session, contract_options=contract
        )
    return built


@pytest.fixture(scope="module")
def graph() -> grimp.ImportGraph:
    """`src/agl/` as import-linter sees it, built once. Nothing is ever checked against this
    object: `_verdicts` copies it first, because a contract check mutates what it is given."""
    session, _ = _contract_options()
    roots: list[str] = list(session["root_packages"])
    external = str(session.get("include_external_packages", "")) in ("True", "true")
    built = grimp.build_graph(*roots, include_external_packages=external)
    assert external, (
        f"{CONFIG_FILE} no longer sets `include_external_packages`, so `claude_agent_sdk` and "
        f"`rich` are not in the graph and contract 3 has nothing to forbid. It would be reported "
        f"kept against every fabrication this file can make."
    )
    return built


def _verdicts(
    contracts: Mapping[str, Contract], graph: grimp.ImportGraph, probe: Probe | None = None
) -> frozenset[str]:
    """Which contracts are broken, over a private copy of `graph` with `probe` fabricated into it.

    One copy per contract, not one per call: `remove_ignored_imports` strips the ignored edges out
    of the graph a `forbidden` or `layers` contract is checking, so a second contract handed the
    same object would be reading a tree the first one had edited.
    """
    broken: set[str] = set()
    for number, contract in contracts.items():
        working = copy.deepcopy(graph)
        if probe is not None:
            working.add_import(importer=probe.importer, imported=probe.imported)
        if not contract.check(working, verbose=False).kept:
            broken.add(number)
    return frozenset(broken)


# --- The probes ----------------------------------------------------------------------------------


def test_every_contract_is_kept_on_the_unmodified_graph(
    contracts: Mapping[str, Contract], graph: grimp.ImportGraph
) -> None:
    """The case that makes every failing case below mean something.

    A probe asserts a contract went from kept to broken. This is the first half of that, taken once
    rather than nine times, and it is also the assertion that this file agrees with `scripts/check`:
    if `lint-imports` passes and this fails, the two are reading different configurations.
    """
    broken = _verdicts(contracts, graph)
    assert not broken, (
        f"contracts {sorted(broken)} are broken on the repository as it stands, before this file "
        f"fabricates anything. Every probe below asserts a contract went from kept to broken, and "
        f"a contract that starts broken makes its probe pass for no reason. Run "
        f"`.venv/bin/lint-imports` and fix the tree first."
    )


@pytest.mark.parametrize("probe", PROBES, ids=lambda probe: f"{probe.contract}:{probe.shown}")
def test_the_named_contract_breaks_on_the_violation_it_exists_to_catch(
    probe: Probe, contracts: Mapping[str, Contract], graph: grimp.ImportGraph
) -> None:
    """One fabricated import, and the contract that is supposed to notice, noticing."""
    assert probe.contract in contracts, (
        f"there is no contract {probe.contract} in {CONFIG_FILE}. Contract numbers are stable by "
        f"policy - see that file's header - so a renumbering is a change to this file, to "
        f"tests/test_contract_listings.py, and to every failure report that cites a number."
    )
    for endpoint in (probe.importer, probe.imported):
        assert endpoint in graph.modules, (
            f"{endpoint} is not in the import graph, and `add_import` would invent it. This probe "
            f"would then fabricate a violation between modules that do not exist, and contract "
            f"{probe.contract} would be consulted about nothing. Fix the name in this file, or - "
            f"if the module really is gone - the contract that still names it."
        )

    broken = _verdicts(contracts, graph, probe)

    assert probe.contract in broken, (
        f"contract {probe.contract} was reported kept with `{probe.shown}` in the graph, which is "
        f"{probe.rule}. That contract is not enforcing the rule it is named for: the import it "
        f"exists to refuse is one it accepts. Contracts reported broken by this fabrication: "
        f"{sorted(broken) or 'none at all'}."
    )
    assert broken == probe.breaks, (
        f"`{probe.shown}` breaks contracts {sorted(broken)}, and this probe records "
        f"{sorted(probe.breaks)}. Contract {probe.contract} still fired, so the rule holds - what "
        f"moved is the overlap between contracts, and that is worth a deliberate edit here rather "
        f"than a silent one. A contract that has stopped catching what it used to catch is the "
        f"reading to rule out first."
    )


def test_contract_1_breaks_on_a_top_level_member_no_layer_declares(
    contracts: Mapping[str, Contract], graph: grimp.ImportGraph
) -> None:
    """Contract 1's third claim, and the one it did not always make.

    `layers =` used to name absolute modules and had no opinion about a module it did not mention,
    so a new top-level package was not at the bottom of the stack but outside it - free to import
    `agl.ports` and `agl.adapters` directly, and be imported by anything, with all six contracts
    reported kept. A hand-maintained comparison in `tests/test_contract_listings.py` was what
    noticed. That was replaced with `containers = agl` plus `exhaustive = True`, which is the
    linter saying the same thing natively, and this is that rule under the same discipline as the
    rest of this file: it is not enough that the flag is in the config, the failure has to happen.

    The fabrication is a module and not an import, because that is the shape of the defect - a
    package that imports nothing at all is still outside the stack. `add_module` is also the one
    call here that does not invent things silently, so the guard runs the other way: the name has
    to be absent before it is added.
    """
    assert UNDECLARED_MEMBER not in graph.modules, (
        f"{UNDECLARED_MEMBER} already exists, so adding it fabricates nothing and this test "
        f"asserts only that the tree is currently legal. Pick a name src/agl/ does not hold."
    )
    assert not _verdicts(contracts, graph), "the graph is already broken; see the anchor test"

    broken: set[str] = set()
    for number, contract in contracts.items():
        working = copy.deepcopy(graph)
        working.add_module(UNDECLARED_MEMBER)
        if not contract.check(working, verbose=False).kept:
            broken.add(number)

    assert broken == {"1"}, (
        f"a top-level member of agl that no layer declares left contracts {sorted(broken)} broken, "
        f"and contract 1 is supposed to be the one of them. `exhaustive = True` requires every "
        f"child of the `agl` container to appear in `layers =`; without it - or with `containers` "
        f"removed, which silently disables it - an unlisted package is unpoliced by anything."
    )


# --- That the six above are the six there are ----------------------------------------------------


def test_every_contract_in_the_file_has_a_probe(contracts: Mapping[str, Contract]) -> None:
    """A seventh contract added without a probe is a rule nobody has watched work.

    This is the assertion that keeps this file from decaying the way the thing it tests decayed:
    the probes are a hand-written table, so without this they cover whatever they covered on the
    day they were written.
    """
    probed = {probe.contract for probe in PROBES} | {"1"}
    unprobed = sorted(set(contracts) - probed)
    assert not unprobed, (
        f"contracts {unprobed} in {CONFIG_FILE} have no probe in this file, so nothing in this "
        f"suite has ever seen them refuse an import. Add a row to PROBES fabricating the violation "
        f"each one exists to catch - the fabrication differs in kind by contract type, so read the "
        f"contract before writing one."
    )


def test_no_probe_names_a_contract_the_file_does_not_have(
    contracts: Mapping[str, Contract],
) -> None:
    """The other direction: a probe of a contract that was deleted or renumbered."""
    stale = sorted({probe.contract for probe in PROBES} - set(contracts))
    assert not stale, (
        f"PROBES names contracts {stale}, which {CONFIG_FILE} does not define. A probe of a "
        f"contract that is not there tests nothing; either the contract was deleted and this row "
        f"goes with it, or numbers moved and the policy that they do not needs revisiting."
    )


def test_each_contract_is_still_the_kind_of_contract_its_probe_assumes() -> None:
    """A number means a rule *and* a kind, and the fabrications are chosen against the kind.

    Contract 4 is `independence`, so its fabrication is an import between two named siblings;
    contract 1 is `layers`, so its fabrications are an import across levels and a member outside
    them. Turn one into the other and the probe still runs, still passes on some verdict, and no
    longer measures what its row says it measures.
    """
    _, options = _contract_options()
    declared = {str(contract["id"]): str(contract["type"]) for contract in options}
    assert declared == dict(CONTRACT_TYPES), (
        f"the contracts in {CONFIG_FILE} are {declared}, and this file expects "
        f"{dict(CONTRACT_TYPES)}. If a contract legitimately changed kind, its probe is the next "
        f"thing to change: a fabrication that is right for one kind passes for the wrong reason "
        f"against another."
    )
