"""`RoutingAgentRunner` - one `AgentRunner` over many, dispatching on `task.model.provider`.

A workflow names a model beside the prompt because the reason for the choice is semantic, and
`ports/agent.py` turns that name into a `Provider` through `ModelId.provider`. This module is the
whole of what happens next: it holds one adapter per provider, assembled once at the composition
root out of whatever is configured and installed, and hands each call to the one adapter that serves
the model the call names. **A workflow sees one `AgentRunner` and never learns which adapter served
it** - there is no "which backend was this" on the way out, because `AgentOutcome` has no field for
one and adding it would be §1.1's leak arriving through the one module with a reason to want it.

## It may import other adapters, and does not

`.importlinter`'s contract 4 excludes this module from adapter independence, and
`tests/test_contract_listings.py` exempts it in the same words: dispatching to the vendor runners is
its whole job, so it may name them. **The permission is not used, and that is the design rather than
an omission.** The adapters arrive as a `Mapping[Provider, AgentRunner]` built by
`config/container.py`, the only module that may construct one (ARCHITECTURE.md §2) - so nothing here
holds a vendor's name, an import of one, or a table of which providers have adapters written for
them. A provider that arrives in a later stage is one more entry the container puts in the mapping,
and not a line in this file.

What the exemption still buys is the room to change that without an architecture argument first, and
it is worth keeping for the same reason it was granted. It is recorded here so that the next reader
meets an unused permission as a decision rather than as a loose end.

## An unknown provider fails loudly as an `InputError`, and the distinction it turns on

Two facts look alike from a stack trace and send a reader to two different places:

  * **A `ModelId` whose prefix names no `Provider` at all** is `ModelId.provider`'s own refusal, and
    the port makes it an `InternalError` - model ids are that module's own enum members and nobody
    types one, so a malformed one was written in our source. Nothing here catches it, wraps it or
    softens it. Exit 70 and a bug report against `ports/agent.py` is what it deserves, and
    translating it into a refusal about configuration would send a reader hunting through a settings
    file for a typo that is in the framework.
  * **A `Provider` this runner holds no adapter for** is an `InputError`. Everything the caller
    supplied is well-formed: the model exists, the provider exists, and what is absent is an adapter
    that was not configured or not installed on this machine. Exit 2, and the reader is sent to the
    configuration that decided which providers this run was assembled with. §3.2 settles the class
    in as many words - "an adapter handed a `ModelId` it does not serve raises `InputError`; it
    never silently substitutes" - and a routing runner asked for a provider it does not hold is
    exactly an adapter handed a model it does not serve. Both fakes and both vendor runners already
    refuse an unserved model with that class and a message naming what they do serve, so a workflow
    author meets one kind of refusal whether the provider is missing or a model within it is.

Not `NotFoundError`, though "well-formed and not there" is its own summary. That class is for a name
the caller went looking for - a run label, a workflow, a git ref - and here the caller named a
*model*, not an adapter; the missing thing is a fact about how this process was assembled rather
than something absent from a world the caller was addressing. `InputError`'s "nothing was attempted"
is also literally true at this line, which is the half a reader acts on.

And never a substitution. Serving `openai:sol` on a Claude adapter because one happens to be present
answers a different question than the workflow asked, which is the whole reason the model is named
beside the prompt.

## Why all three members take a `ModelId`, seen from the one implementation that needs it

`ports/agent.py` gives this class as the reason `capabilities()` and `check_ready()` are not
argument-free: "the routing runner is an `AgentRunner` like any other, and one asked 'what can you
do' with no model named could only answer for some provider or other, which is a lie in the shape of
an answer." Every other implementation checks the model and then answers the same thing for all of
them. Here the argument *is* the answer's address: strip it and there is no dispatch, so preflight
would be asking one question and getting some backend's answer to it. The three members below are
each one line for that reason, and the line is the same line.

## Both callbacks go straight through, and dropping one would be invisible

`run` passes `on_question` and `on_activity` on untouched. Neither is stored, wrapped, defaulted or
filtered, and nothing here is per-call state - the mapping is the whole of what an instance holds,
which is what lets one router serve a workflow's two concurrent reviewers exactly as one adapter
does.

The reason to say it rather than let it be read off two keywords is what a mistake would cost.
Dropping `on_question` turns every run into the port's *second* edge case - the agent is told no
answer is available and carries on - against a role that preflight admitted precisely because
`capabilities()` reported `MID_RUN_QUESTIONS`; the negotiation simply stops happening. Dropping
`on_activity` is worse to find: the contract suite asserts only that whatever arrives is a `str`,
and an adapter with nothing to report calls it never, so a router that swallowed every line would
pass the suite it inherits and show up as a dashboard that has gone quiet.
"""

from collections.abc import Mapping
from typing import Final

from agl.ports.agent import (
    ActivityReporter,
    AgentOutcome,
    AgentRunner,
    AgentTask,
    Capability,
    ModelId,
    Provider,
    QuestionHandler,
)
from agl.ports.errors import InputError

__all__ = ["RoutingAgentRunner"]


class RoutingAgentRunner(AgentRunner):
    """One `AgentRunner` over one adapter per provider. The port in full, and no backend of its own.

    It implements the same ABC as the things it holds, which is not a nicety: `config/container.py`
    builds one of these and puts it in the services bundle, and everything above - preflight, the
    engine, a workflow's step - addresses it through `AgentRunner` and cannot tell it apart from a
    runner with a harness behind it. That is the requirement (§3.2) and it is also the whole reason
    this class can exist without a vocabulary of its own.

    Nothing is added on the way through. No capability is intersected, no readiness is cached, no
    outcome is annotated, and no run is retried against a second provider. Each would be this
    module inventing a policy the port did not ask any adapter for and no workflow could turn off.
    """

    def __init__(self, runners: Mapping[Provider, AgentRunner]) -> None:
        """`runners` is one adapter per provider, and the mapping is the whole of what this holds.

        **A mapping keyed by `Provider`, because that is the shape the port describes**: "one
        adapter per member, held by the routing runner and nowhere else". A sequence of runners
        could not be keyed at all - an `AgentRunner` cannot be asked which provider it serves, there
        is no member for it, and adding one would be a vendor's identity crossing the port to make
        this class's bookkeeping easier, which is §1.1's leak in its most plausible clothing. So the
        pairing is data the container states, and the type says so.

        **Two adapters claiming one provider is unrepresentable here rather than refused**, and that
        follows from the same choice: one key holds one runner, so the mapping cannot carry the
        disagreement in the first place. Taking pairs and checking for a duplicate would buy a
        refusal for a mistake the parameter type otherwise makes impossible to express - at the cost
        of a caller having to build a shape nobody wants for any other reason. What is left is one
        line of `dict()` in a caller that composes the mapping from pairs, and that resolution is in
        the caller's own code where a reader can see it.

        **An empty mapping is an `InputError`**, because a router over no adapters serves nothing:
        every run through it would fail one at a time, at the step rather than at the composition
        root, each with a message about a provider when the real fact is that this bundle was built
        with no agent backend at all. The port's convention is that a constructor refusing what it
        was handed refuses it as `InputError` - nothing has been attempted, and exit 2 sends the
        reader to the configuration that decides which providers a run is assembled with.

        Copied on the way in, for `Tool.payload_schema`'s reason: a caller that kept the dict it
        passed cannot re-point this runner's routing table halfway through a run.
        """
        if not runners:
            raise InputError(
                "a routing agent runner was built with no adapters at all, and one holding no "
                "adapter serves no model: every step of every workflow would fail at the step it "
                "reached, naming the provider it wanted, when the fact worth reporting is that "
                "this run was assembled with no agent backend. Configure at least one provider and "
                "install the harness it names"
            )
        self._runners: Final = dict(runners)

    async def capabilities(self, model: ModelId) -> frozenset[Capability]:
        """What the adapter serving `model` can be asked for, answered by that adapter.

        The `ModelId` is not checked here and then ignored, as it is in an adapter that serves one
        backend - it is the address the question is put to. This class holds no capability table and
        could not honestly build one: "what can you do" over several backends has no answer that is
        not either a union nothing can deliver or an intersection that would refuse roles a
        perfectly good adapter supports. Preflight asks per model (§3.2) for exactly that reason.
        """
        return await self._serving(model).capabilities(model)

    async def check_ready(self, model: ModelId) -> None:
        """Whether the adapter serving `model` can serve it right now. Returns nothing, or raises.

        One provider, because that is what was asked about. §3.2's first preflight check walks the
        providers a workflow's roles actually name and calls this once for each, so a run needing
        two of them dies at second zero on the missing one - and a routing runner that probed all
        of its adapters here would fail a Claude-only workflow on an unauthenticated session it was
        never going to use.

        `UpstreamUnavailable` from the adapter reaches the caller unchanged, which is the whole
        point: preflight catches that class alone, and a router that wrapped it in anything of its
        own would turn a logged-out session into an exit 70 telling somebody to file a bug.
        """
        await self._serving(model).check_ready(model)

    async def run(
        self,
        task: AgentTask,
        *,
        on_question: QuestionHandler | None = None,
        on_activity: ActivityReporter | None = None,
    ) -> AgentOutcome:
        """Run `task` on the adapter serving `task.model`, and hand back what it answered.

        Both callbacks pass through untouched - see the module docstring for what dropping either
        would cost and why no contract test would notice one of them. The `AgentOutcome` comes back
        untouched for the same reason in the other direction: a stop reason of `None` means the
        backend did not say, and a router that filled it in would be inventing the one fact the port
        went out of its way to let a backend decline to state.

        The dispatch happens before anything else, which is not an ordering worth arranging - it is
        the only thing this method does that is its own.
        """
        return await self._serving(task.model).run(
            task, on_question=on_question, on_activity=on_activity
        )

    def _serving(self, model: ModelId) -> AgentRunner:
        """The adapter that serves `model`, or `InputError` naming what this runner was built with.

        `model.provider` is the port's own derivation and its own refusal: a member whose prefix
        names no provider raises `InternalError` from there and passes through here untouched, since
        that is our typo in `ports/agent.py` and not a fact about anybody's configuration. What this
        method adds is the other half - a real provider that this bundle holds no adapter for - and
        the module docstring argues at length why the two are different errors.

        The message names the providers that *are* held, because that is what turns "it did not
        work" into a decision: configure the one that is missing, or name a model from one that is
        there. It does not name the adapters behind them - a workflow author never learns which
        adapter served a run, and a failure is not the place to start telling them.
        """
        provider = model.provider
        runner = self._runners.get(provider)
        if runner is None:
            held = sorted(str(member) for member in self._runners)
            raise InputError(
                f"nothing here can run {str(model)!r}: it is served by {str(provider)!r}, and this "
                f"run was assembled with an adapter for {held} and nothing else. A provider "
                f"arrives with an adapter, so either that provider is not configured or its "
                f"harness is not installed on this machine. No other model is substituted for this "
                f"one - the model was named beside the prompt because the choice was semantic, and "
                f"answering with a different one answers a different question than the one asked"
            )
        return runner
