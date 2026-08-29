"""What the params model promises: named flags in, a frozen instance and a record out.

Four properties carry this suite. **The worked example** is parsed literally - `TicketsParams`
below, from what `agl run tickets -n auth -r "add oauth" -c 4` leaves behind - so a change breaking
that shape breaks a test quoting it. **Every refusal is an `InputError`**,
asserted on the class and never on "it raised": `argparse` refuses by calling `sys.exit(2)`, so a
suite accepting a `SystemExit` would pass against exactly the bug this module exists to prevent.
**No positional ever reaches `argparse`**, asserted against the built parser and not against a parse
that happened to work - a parse proves only that nothing needed one. And **what `to_json` renders
survives `json.dumps` and `RunSpec`**, because a parameter that cannot be written down is a run that
cannot resume.

A fifth arrived one direction over: **`from_json` is `to_json`'s inverse and refuses everything
that is not it.** `agl resume <label>` reads the record instead of a command line, so the read side
is what makes "params come from `run.json`" true - and it is a refusal point rather than a coercion
point, which is a claim only a test that hands it `"4"` where a record held `4` can hold still. The
section at the bottom is that, plus the one widening the round trip actually needs.

Declaration faults are pinned where they are written, since a workflow package that
cannot be invoked correctly should fail when it is imported rather than when somebody types a flag;
and a refusal is checked on its message wherever that message carries the fact the reader needs
next, which field or flag or type it was.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from agl.ports.errors import InputError
from agl.ports.ids import RunLabel
from agl.ports.run import RunSpec
from agl.sdk.params import RefusingParser, arg, from_json, parse, parser_for, to_json


@dataclass(frozen=True)
class TicketsParams:
    """The worked example. Every assertion below is about this one declaration."""

    request: str = arg("-r", "--request", help="what to build")
    concurrent: int = arg("-c", "--concurrent", default=3)


@dataclass(frozen=True)
class Mixed:
    """One field of every supported type, so that a rule can be checked against all four at once."""

    request: str = arg("-r", "--request")
    concurrent: int = arg("-c", "--concurrent", default=3)
    ratio: float = arg("--ratio", default=1.5)
    verbose: bool = arg("-v", "--verbose", default=False)


@dataclass(frozen=True)
class NoParams:
    """A workflow that takes nothing - `noop`'s shape, and every workflow needs one anyway."""


@dataclass(frozen=True)
class Widening:
    """A `float` field whose default is an `int` - legal, and what `from_json` has to admit back.

    `arg()` takes any of the four as a default and only `bool` has a rule about its own, so a run
    where `--ratio` went unpassed holds the `int` 3 and `to_json` stores an `int`. A read side
    demanding a `float` would refuse a record AGL itself wrote.
    """

    ratio: float = arg("--ratio", default=3)


@dataclass(frozen=True)
class Unstorable:
    """A field type `arg()` will declare and neither direction can carry.

    `parser_for` refuses it at the parse, naming the field, and never sees it again; `from_json` is
    reached without a parse at all - `agl resume` reads a record - so it has to refuse it too.
    """

    tags: list[str] = arg("--tags")


# --- the worked example --------------------------------------------------------------------------


def test_the_worked_example_parses_as_it_is_written() -> None:
    """`agl run tickets -n auth -r "add oauth" -c 4`, minus what the generic parser already took.
    The promise is that "mypy knows `run.params.concurrent` is an `int`", so the runtime has to
    agree."""
    params = parse(TicketsParams, ["-r", "add oauth", "-c", "4"])
    assert params == TicketsParams(request="add oauth", concurrent=4)
    assert type(params.concurrent) is int


def test_the_long_spelling_is_the_same_flag() -> None:
    assert parse(TicketsParams, ["--request", "x", "--concurrent", "4"]).concurrent == 4


def test_an_absent_optional_flag_leaves_the_dataclasss_own_default() -> None:
    """`SUPPRESS` is what makes this true: `argparse` is never told 3, so it cannot disagree."""
    assert parse(TicketsParams, ["-r", "x"]) == TicketsParams(request="x", concurrent=3)


def test_a_workflow_with_no_parameters_parses_an_empty_argv() -> None:
    assert parse(NoParams, []) == NoParams()


# --- refusals at the parse, every one of them an InputError --------------------------------------


def test_a_missing_required_flag_is_an_input_error() -> None:
    """A field with no default is a required flag, and the parse refuses before anything runs."""
    with pytest.raises(InputError, match="--request"):
        parse(TicketsParams, ["-c", "4"])


def test_a_value_that_will_not_convert_is_an_input_error_and_not_a_system_exit() -> None:
    """`argparse` would `sys.exit(2)` here, which is the right number reached the wrong way: it
    bypasses `ports/errors.py`'s one table, so a `SystemExit` escaping is the failure."""
    with pytest.raises(InputError, match="invalid int value"):
        parse(TicketsParams, ["-r", "x", "-c", "banana"])


def test_an_unknown_flag_is_an_input_error() -> None:
    with pytest.raises(InputError, match="--nope"):
        parse(TicketsParams, ["-r", "x", "--nope", "1"])


def test_an_abbreviated_flag_is_not_a_flag() -> None:
    """`allow_abbrev=False`: the accepted spellings are the declared ones, so that adding a flag
    later cannot make a spelling somebody already types ambiguous."""
    with pytest.raises(InputError, match="--conc"):
        parse(TicketsParams, ["-r", "x", "--conc", "4"])


def test_the_refusing_parser_raises_where_argparse_would_exit() -> None:
    """Exported for the generic `run` parser, so pinned here directly and not only through a params
    class. The usage line rides with the message: a refusal listing the flags is worth more."""
    with pytest.raises(InputError, match="usage"):
        RefusingParser(prog="agl run").error("something the caller typed")


# --- refusals at the declaration -----------------------------------------------------------------


def test_a_declared_positional_is_refused_where_it_is_written() -> None:
    """`agl run <workflow>` already occupies that position, so a flagless field is refused."""
    with pytest.raises(InputError, match="positional"):
        arg("request")


def test_a_declaration_with_no_flags_is_refused() -> None:
    with pytest.raises(InputError, match="at least one flag"):
        arg()


@pytest.mark.parametrize(
    "flag", ["request", "-", "--", "-abc", "-1", "--1st", "--a=b", "--a b", "--café", "---x"]
)
def test_a_flag_is_a_dash_and_a_letter_or_two_dashes_and_a_name(flag: str) -> None:
    """The allowlist, spelled as its counterexamples. `-abc` is refused although `argparse` takes
    it, and `-1` because one such declaration changes how every other argument on the line reads."""
    with pytest.raises(InputError, match="cannot be a workflow's flag"):
        arg(flag)


@pytest.mark.parametrize("flag", ["-r", "--request", "--dry-run", "--max_concurrent", "--x2"])
def test_the_spellings_a_workflow_may_actually_want(flag: str) -> None:
    """The other half of the allowlist: refusing too much would be as bad as refusing too little."""
    assert arg(flag) is not None


def test_an_unsupported_field_type_is_refused_by_name() -> None:
    """The message names the field and the annotation, because those are what has to be changed."""

    @dataclass(frozen=True)
    class Bad:
        tags: list[str] = arg("-t", "--tags")

    with pytest.raises(InputError, match=r"Bad\.tags is a list\[str\]"):
        parser_for(Bad)


def test_a_default_of_an_unsupported_type_is_refused_before_the_class_exists() -> None:
    """`arg()` sees the default even though it cannot see the annotation, so it says so first."""
    with pytest.raises(InputError, match="is a tuple"):
        arg("-o", default=("a", "tuple"))


def test_a_field_declared_without_arg_is_refused() -> None:
    """Every field of a params dataclass is a flag: one that is not could never be given a value."""

    @dataclass(frozen=True)
    class Bad:
        smuggled: int = 3

    with pytest.raises(InputError, match="not declared with `arg\\(\\)`"):
        parser_for(Bad)


def test_two_fields_may_not_claim_one_flag() -> None:
    """`argparse` would raise its own `ArgumentError` here, which is not an `AglError` at all."""

    @dataclass(frozen=True)
    class Bad:
        first: int = arg("-c", "--first", default=1)
        second: int = arg("-c", "--second", default=2)

    with pytest.raises(InputError, match="both declare '-c'"):
        parser_for(Bad)


def test_a_params_class_that_is_not_a_dataclass_is_refused() -> None:
    class NotADataclass:
        pass

    with pytest.raises(InputError, match="not a dataclass"):
        parser_for(NotADataclass)


def test_a_field_whose_annotation_cannot_be_resolved_is_refused() -> None:
    """A stringised annotation naming nothing is the declaration's fault, not a crash of ours."""

    @dataclass(frozen=True)
    class Bad:
        thing: NoSuchType = arg("-t")  # type: ignore[name-defined] # noqa: F821

    with pytest.raises(InputError, match="cannot be resolved"):
        parser_for(Bad)


# --- no positionals, ever ------------------------------------------------------------------------


def test_the_built_parser_holds_no_positional_action() -> None:
    """No positional ever reaches `argparse`, asserted against the parser and not a lucky parse.
    `_actions` is private and there is no public accessor; the alternative is to assert nothing."""
    parser = parser_for(Mixed)
    assert [action for action in parser._actions if not action.option_strings] == []


# --- bool is a switch ----------------------------------------------------------------------------


def test_a_bool_field_is_a_value_less_switch() -> None:
    assert parse(Mixed, ["-r", "x"]).verbose is False
    assert parse(Mixed, ["-r", "x", "-v"]).verbose is True


def test_a_switch_takes_no_value() -> None:
    """`-v true` would have to mean something, and `bool("false")` is `True`: it means nothing."""
    with pytest.raises(InputError, match="unrecognized arguments"):
        parse(Mixed, ["-r", "x", "-v", "true"])


def test_a_bool_field_that_does_not_default_to_false_is_refused() -> None:
    """Required, it can only ever be True; defaulting to True, it can never be turned off. Both are
    a flag with one reachable state, which is a flag that carries no information."""

    @dataclass(frozen=True)
    class RequiredSwitch:
        force: bool = arg("-f", "--force")

    @dataclass(frozen=True)
    class OnByDefault:
        force: bool = arg("-f", "--force", default=True)

    for params in (RequiredSwitch, OnByDefault):
        with pytest.raises(InputError, match="must be declared `default=False`"):
            parser_for(params)


# --- the record ----------------------------------------------------------------------------------


def test_the_rendered_mapping_is_the_fields_by_name() -> None:
    rendered = to_json(parse(Mixed, ["-r", "add oauth", "-c", "4", "-v"]))
    assert dict(rendered) == {
        "request": "add oauth", "concurrent": 4, "ratio": 1.5, "verbose": True
    }


def test_the_rendered_mapping_round_trips_through_json_and_into_a_run_spec() -> None:
    """Params are "persisted into `run.json`, which is why `agl resume auth` takes no flags".
    `RunSpec.params` receives this and `json` writes it, so both are exercised rather than assumed:
    a mapping this module is happy with and `json` is not is a run never written down."""
    rendered = to_json(parse(TicketsParams, ["-r", "add oauth", "-c", "4"]))
    assert json.loads(json.dumps(dict(rendered))) == {"request": "add oauth", "concurrent": 4}
    spec = RunSpec(
        workflow="tickets",
        workflow_version="1.0.0",
        label=RunLabel("auth"),
        base_ref="main",
        base_sha="8c19f7ae4d2b0913e5f6" * 2,
        branch="agl/auth",
        params=rendered,
        created_at=datetime(2026, 8, 18, 9, 14, 2, tzinfo=UTC),
    )
    assert spec.to_json()["params"] == {"request": "add oauth", "concurrent": 4}


def test_the_rendered_mapping_cannot_be_written_through() -> None:
    with pytest.raises(TypeError):
        to_json(parse(TicketsParams, ["-r", "x"]))["request"] = "something else"  # type: ignore[index]


def test_to_json_refuses_the_class_rather_than_rendering_its_defaults() -> None:
    with pytest.raises(InputError, match="not an instance"):
        to_json(TicketsParams)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_a_non_finite_float_is_refused_here_rather_than_as_our_bug(value: float) -> None:
    """`-c inf` parses - `float("inf")` succeeds - and `json` then writes a bare token no reader
    accepts. `ports/run.py` calls that an `InternalError`, exit 70, "file a bug against AGL", which
    is the wrong thing to tell somebody who typed it. Refused here, as the exit 2 it is."""
    with pytest.raises(InputError, match="`run.json` cannot"):
        to_json(Mixed(request="x", ratio=value))


def test_a_surrogate_is_refused_here_for_the_same_reason() -> None:
    """What `os.fsdecode` makes of a command-line byte that is not UTF-8. Nothing can encode it."""
    with pytest.raises(InputError, match="`run.json` cannot"):
        to_json(TicketsParams(request="a\udcffb"))


def test_a_value_of_no_storable_type_is_refused() -> None:
    """A params instance can be built by hand, so the render checks rather than assumes."""
    with pytest.raises(InputError, match="`run.json` cannot"):
        to_json(TicketsParams(request=object()))  # type: ignore[arg-type]


# --- reading the record back ----------------------------------------------------------------------


def test_the_record_round_trips_back_into_the_instance_it_was_rendered_from() -> None:
    """`from_json` is `to_json`'s inverse for every type `arg()` admits - which is the whole claim.

    All four in one instance, because the read side dispatches per field type and a test over one
    of them would say nothing about the other three. Equality is the assertion and the types come
    with it: a dataclass compares field by field, and `4 == 4.0` is true, so `type` is asked
    separately for the two that could be confused.
    """
    given = parse(Mixed, ["-r", "add oauth", "-c", "4", "--ratio", "2.5", "-v"])

    read_back = from_json(Mixed, dict(to_json(given)))

    assert read_back == given
    assert type(read_back.concurrent) is int
    assert type(read_back.ratio) is float


def test_the_record_round_trips_through_json_as_the_real_store_writes_it() -> None:
    """The path an actual resume takes: `to_json`, `RunSpec`, a file, `json.loads`, and back.

    The in-memory store hands a copy of the mapping straight back, so a `from_json` that only ever
    saw one would be tested against values that never met an encoder. `json` is what the filesystem
    store puts between the two directions, and it is the thing that could quietly change a type.
    """
    stored = json.loads(json.dumps(dict(to_json(parse(TicketsParams, ["-r", "add oauth"])))))

    assert from_json(TicketsParams, stored) == TicketsParams(request="add oauth", concurrent=3)


def test_a_workflow_with_no_parameters_reads_back_from_an_empty_record() -> None:
    assert from_json(NoParams, {}) == NoParams()


def test_an_int_is_admitted_where_a_float_is_declared() -> None:
    """The one widening, and it is the round trip rather than a courtesy - see `_ADMITTED`.

    `--ratio` is never passed, so the instance holds the `int` its declaration defaulted to and the
    record stores an `int`. A read side demanding a `float` back would refuse a record `to_json`
    produced, which is the one thing an inverse may not do.
    """
    given = parse(Widening, [])

    assert dict(to_json(given)) == {"ratio": 3}
    assert from_json(Widening, {"ratio": 3}) == given


def test_a_field_the_record_does_not_carry_is_refused_by_name() -> None:
    """A workflow that gained a parameter and kept its version. Named, because "the params do not
    match" leaves the reader to work out which field moved."""
    with pytest.raises(InputError, match="'concurrent'"):
        from_json(TicketsParams, {"request": "add oauth"})


def test_a_key_the_class_does_not_declare_is_refused_by_name() -> None:
    """The other direction: a parameter the workflow dropped. `RunSpec.from_json`'s stance, one
    layer up - a record carrying keys this class does not know was written by another version of
    the workflow, and this refuses records rather than migrating them."""
    with pytest.raises(InputError, match="'urgency'"):
        from_json(TicketsParams, {"request": "x", "concurrent": 3, "urgency": "high"})


def test_a_value_of_another_type_is_refused_rather_than_converted() -> None:
    """The refusal-not-coercion rule, at the one value that makes it tempting.

    `"4"` is what `-c 4` looked like before `argparse` converted it, and converting it here would
    hand the run a parameter nobody chose - and every fingerprint taken over it would be taken over
    a value the first invocation never had. The version stamp is what should have caught this; what
    is left for this module is to be loud rather than helpful.
    """
    with pytest.raises(InputError, match="never converted"):
        from_json(TicketsParams, {"request": "x", "concurrent": "4"})


def test_a_field_type_neither_direction_can_carry_is_refused() -> None:
    """`parser_for` refuses this at the parse and never sees it again; a resume reads a record with
    no parse in front of it, so the read side refuses it too, in the same four-type vocabulary."""
    with pytest.raises(InputError, match="a str, an int, a float or a bool"):
        from_json(Unstorable, {"tags": ["a", "b"]})


def test_from_json_refuses_something_that_is_not_a_params_dataclass() -> None:
    with pytest.raises(InputError, match="not a dataclass"):
        from_json(int, {})
