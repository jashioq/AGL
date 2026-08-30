"""What `run.json` promises: its wire shape, an exact round trip, and params nobody interprets.

Three properties carry this suite. The **wire shape** is written out literally rather than
recomposed, because a later stage reading an older record depends on those eight key names, and a
test that builds them the way the module does agrees with any bug it has. The **round trip** is
checked in both directions and through a real `json.dumps`/`json.loads`, since a `dict` this module
is happy with and `json` is not would be a file never written. And **opacity** - that nothing here
knows what a param is - is checked by putting into `params` the values the framework has opinions
about everywhere else, and watching them come back identical. The corpus from `_corpus.py` is
reused for labels: a name `ids.py` accepts and this cannot read back is a run that cannot resume.
"""

import json
import unicodedata
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Final

import pytest
from _corpus import ACCEPTED, CORPUS, imported_modules, impurities

from agl.ports import run
from agl.ports.errors import InputError, InternalError, exit_code_for
from agl.ports.ids import RunLabel
from agl.ports.run import JsonValue, RunSpec

# An example record, with its `base_sha` doubled to a full sha1 - see `test_the_pin...` for why
# a twenty-character abbreviation cannot be the length the field means.
_ABBREVIATED: Final = "8c19f7ae4d2b0913e5f6"
_SHA: Final = _ABBREVIATED * 2
_SHA256: Final = _ABBREVIATED * 3 + "4d2b"

_WIRE: Final[dict[str, JsonValue]] = {
    "workflow": "tickets",
    "workflow_version": "1.0.0",
    "label": "auth",
    "base_ref": "main",
    "base_sha": _SHA,
    "branch": "agl/auth",
    "params": {"request": "add oauth", "concurrent": 4},
    "created_at": "2026-08-18T09:14:02Z",
}
_SPEC: Final = RunSpec.from_json(_WIRE)


# --- The wire shape, and the round trip ---------------------------------------------------------


def test_the_wire_shape_is_eight_keys_in_one_order_with_those_spellings() -> None:
    """`run.json`, spelled out - eight keys, in that order, with those spellings."""
    assert _SPEC.to_json() == {
        "workflow": "tickets",
        "workflow_version": "1.0.0",
        "label": "auth",
        "base_ref": "main",
        "base_sha": _SHA,
        "branch": "agl/auth",
        "params": {"request": "add oauth", "concurrent": 4},
        "created_at": "2026-08-18T09:14:02Z",
    }
    assert tuple(_SPEC.to_json()) == (
        "workflow", "workflow_version", "label", "base_ref", "base_sha", "branch", "params",
        "created_at",
    )  # fmt: skip
    assert _SPEC.label == RunLabel("auth"), "the label is a validated type, not the string on disk"
    assert _SPEC.created_at == datetime(2026, 8, 18, 9, 14, 2, tzinfo=UTC)


def test_a_record_round_trips_in_both_directions_and_through_a_real_encoder() -> None:
    """`from_json(to_json(spec)) == spec`, `to_json(from_json(wire)) == wire`, and `json` agrees."""
    assert RunSpec.from_json(_SPEC.to_json()) == _SPEC
    assert _SPEC.to_json() == _WIRE
    text = json.dumps(_SPEC.to_json())
    assert RunSpec.from_json(json.loads(text)) == _SPEC
    assert '"created_at": "2026-08-18T09:14:02Z"' in text, "not the `+00:00` isoformat would give"


def test_every_label_ids_accepts_survives_a_round_trip() -> None:
    """Where this suite meets `ids.py`: a run that cannot be read back cannot be resumed."""
    for value in ACCEPTED:
        wire = {**_WIRE, "label": value}
        spec = RunSpec.from_json(wire)
        assert spec.label == RunLabel(value)
        assert spec.to_json() == wire
        assert RunSpec.from_json(json.loads(json.dumps(wire))) == spec


def test_the_keys_are_written_out_so_a_field_rename_cannot_move_the_wire() -> None:
    """The field names match the wire keys today, which is why `to_json` must not read them off."""
    assert tuple(_SPEC.to_json()) == run._WIRE_KEYS
    assert tuple(_SPEC.__dataclass_fields__) == run._WIRE_KEYS


# --- params are opaque --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {}, {"request": "add oauth", "concurrent": 4},
        {"nested": {"deep": {"deeper": [1, 2, {"end": None}]}}},
        {"array": [], "object": {}, "null": None, "true": True, "false": False},
        {"numbers": [0, -1, 2.5, 1e300, -0.0, 10**30]},
        {"unicode": "café 日本語 🍌 \u200b", "ключ": "значение"},
        {"": "the empty key is a key"}, {"quotes": '"\\\n\t', "backslash": "C:\\x"},
        {"label": {"base_sha": ["run.json", {"created_at": None}]}},
        dict.fromkeys(run._WIRE_KEYS, "a param may be named after one of our own fields"),
    ],
)  # fmt: skip
def test_params_are_stored_exactly_as_given(params: dict[str, JsonValue]) -> None:
    """Nested objects, arrays, null, numbers, unicode and our own key names all come back the same.
    Checked on the type *and* through `json`, because the promise is about the file."""
    spec = RunSpec.from_json({**_WIRE, "params": params})
    assert spec.params == params
    assert spec.to_json() == {**_WIRE, "params": params}
    assert json.loads(json.dumps(spec.to_json()))["params"] == params
    assert RunSpec.from_json(spec.to_json()) == spec


def test_a_record_never_shares_mutable_state_with_anything() -> None:
    """Copied in and copied out, so neither the caller's dict nor the emitted one is the record."""
    source: dict[str, JsonValue] = {"outer": {"inner": [1]}}
    spec = RunSpec.from_json({**_WIRE, "params": source})
    source["added"] = True
    assert isinstance(source["outer"], dict)
    source["outer"]["inner"] = ["changed"]
    assert spec.params == {"outer": {"inner": [1]}}, "the record kept a copy, not the caller's dict"

    emitted = spec.to_json()
    emitted["params"] = "gone"
    assert spec.to_json()["params"] == {"outer": {"inner": [1]}}
    with pytest.raises(TypeError):
        spec.params["late"] = 1  # type: ignore[index]


def test_a_tuple_becomes_the_list_it_would_be_on_the_way_back() -> None:
    """Otherwise a params dataclass with a tuple field round-trips to an almost-equal record."""
    with_tuple = replace(_SPEC, params={"tags": ("a", "b")})  # type: ignore[dict-item]
    assert with_tuple.params == {"tags": ["a", "b"]}
    assert RunSpec.from_json(with_tuple.to_json()) == with_tuple


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), object(), b"bytes", {1, 2}, RunLabel("auth")],
)
def test_params_refuse_what_could_not_be_read_back(value: object) -> None:
    """Shape, not meaning: the one question asked is whether the value survives the round trip."""
    with pytest.raises(InternalError):
        replace(_SPEC, params={"p": value})  # type: ignore[dict-item]
    with pytest.raises(InternalError):
        replace(_SPEC, params={"nested": [{"deep": value}]})  # type: ignore[dict-item]


def test_a_param_key_that_is_not_a_string_is_refused_rather_than_renamed() -> None:
    """`json` would write `{1: "a"}` as `{"1": "a"}`, and the record would come back different."""
    with pytest.raises(InternalError, match="keyed by strings"):
        replace(_SPEC, params={1: "a"})  # type: ignore[dict-item]


# --- The one string that cannot be written down -------------------------------------------------


def _has_surrogate(value: str) -> bool:
    """Category `Cs`, asked of Unicode rather than of either module.

    Both modules under comparison below spell this rule for themselves - `ids.py` inside a set of
    categories a name may not hold, `run.py` as the only one a param may not - and a test that
    imported either private constant would agree with whichever of them was wrong.
    """
    return any(unicodedata.category(character) == "Cs" for character in value)


# What a wrong verdict here costs, said once and cited by both tests below. The class alone is not
# the assertion: the class is what a reader of the source sees and the number is what a user sees,
# and it was the number that was wrong.
_WRONG_EXIT: Final = (
    "a lone surrogate came back with an exit code other than 2. It is malformed input - a "
    "command-line byte `sys.argv` decoded with `surrogateescape`, or a value an agent produced - "
    "and 70 would tell whoever hit it that AGL is broken when what is broken is their data. "
    "`journal.py`'s `_checked_text` is this same test over this same category and answers 2"
)


def test_a_surrogate_is_refused_at_write_time_wherever_it_sits() -> None:
    """The one `str` UTF-8 cannot encode, refused as a value, as a key, and at any depth.

    `JsonValue` admits any `str`, and `json.loads('"\\ud800"')` hands back an unpaired UTF-16 code
    unit without complaining, so an agent's reporting-tool payload really can carry one this far.
    `FilesystemStore._encoded` refuses it at the write and argues the whole of why; this refuses it
    at the call that produced it, which is the trade the non-finite float and the non-string key
    above already take. Keys as well as values, because a key reaches the same encoder and takes
    the whole document down rather than one field of it.

    **`InputError`, and the exit code is asserted beside the class.** This module and
    `sdk/_engine/journal.py` each hold a `_checked_text` whose surrogate test is character for
    character the same, and they used to disagree about what it raised - so the same string was
    exit 2 or exit 70 depending only on which module inspected it first. Both say `InputError`
    now, for the reason `_WRONG_EXIT` gives: a lone surrogate arrives from outside, and the two
    messages are kept different because the consequences they name are different and both real.
    """
    for surrogate in ("\ud800", "\udfff", "before \udc00 after"):
        with pytest.raises(InputError, match="surrogate") as as_value:
            replace(_SPEC, params={"p": surrogate})
        assert exit_code_for(as_value.value) == 2, _WRONG_EXIT
        with pytest.raises(InputError, match="surrogate") as as_key:
            replace(_SPEC, params={surrogate: "in a key"})
        assert exit_code_for(as_key.value) == 2, _WRONG_EXIT

    with pytest.raises(InputError, match="surrogate"):
        replace(_SPEC, params={"nested": [{"deep": "\ud800"}]})
    with pytest.raises(InputError, match="surrogate"):
        replace(_SPEC, params={"nested": [{"\ud800": "a key three containers down"}]})

    assert replace(_SPEC, params={"astral": "\U0001f34c"}).params == {"astral": "\U0001f34c"}, (
        "a character outside the BMP is a surrogate *pair* in UTF-16 and perfectly good UTF-8; "
        "refusing it would refuse the emoji a workflow's summary is entitled to hold"
    )


def test_a_surrogate_ids_refuses_in_a_name_is_refused_here_too_and_nothing_else_is() -> None:
    """The parity, in both directions, over the corpus `ids.py`'s own suite is checked against.

    One rule, two layers, **one error class**: `ids.py` says `InputError` because a user typed a
    name that has to become a path segment, and this says `InputError` because the value reached
    the record from outside too - a param off a command line, a value an agent produced - and exit
    2 is the answer that sends whoever produced it back to their own data. The values are the same
    values, and the corpus is what holds the two together - so the day either door widens or
    narrows, the disagreement shows up here.

    The second half is the one that matters more, because the two rules are deliberately *not*
    equal. `ids.py` turns away almost the whole corpus - a space, a shell metacharacter, `café`, a
    banana - and every one of those is a param somebody is entitled to pass. What this asserts is
    that the shared rule is category `Cs` and that nothing else came across with it.
    """
    refused = [value for value in CORPUS if _has_surrogate(value)]
    assert len(refused) > 1, "the corpus carries no surrogate, so this compares two empty sets"
    for value in refused:
        with pytest.raises(InputError, match="cannot be used") as as_name:
            RunLabel(value)
        with pytest.raises(InputError, match="surrogate") as as_value:
            replace(_SPEC, params={"p": value})
        with pytest.raises(InputError, match="surrogate") as as_key:
            replace(_SPEC, params={value: "in a key"})
        assert {exit_code_for(caught.value) for caught in (as_name, as_value, as_key)} == {2}, (
            _WRONG_EXIT
        )

    kept = {value: value for value in CORPUS if not _has_surrogate(value)}
    assert len(kept) > len(ACCEPTED), "the corpus accepted here must exceed what a name may be"
    assert replace(_SPEC, params=kept).params == kept
    assert json.loads(json.dumps(replace(_SPEC, params=kept).to_json()))["params"] == kept

    for legal_param in ("a b", "café", "🍌", "a\nb", "$(whoami)", ".hidden", "", "_work"):
        with pytest.raises(InputError):
            RunLabel(legal_param)
        one_param: dict[str, JsonValue] = {legal_param: legal_param}
        assert replace(_SPEC, params=one_param).params == one_param


def test_the_ref_a_run_starts_from_is_checked_the_way_a_param_is() -> None:
    """The third seam, and the one nothing walked: a `str` field of the record itself.

    The two seams above are a *step's* inputs and a run record's `params`, and both are values
    somebody put inside a container this module or `journal.py` walks. `base_ref` is neither. It is
    a field of `RunSpec`, it goes into `to_json()` verbatim with nothing between it and
    `Store.write_record`, and there `FilesystemStore._encoded` does `text.encode("utf-8")` - a
    `UnicodeEncodeError`, which is a `ValueError`, which both stores translate into `InternalError`.
    Exit 70 for a string a person typed, which is why the check belongs here beside `_check_sha`
    rather than at the port that would report it as AGL's own bug.

    **The path is real, and the range of the surrogate is what makes it real.** `agl run --from
    <ref>` is read off `sys.argv`, which Python decodes with `surrogateescape`, so an undecodable
    byte on the command line mints exactly one lone surrogate and only ever in `\\udc80`-`\\udcff`.
    Those are precisely the ones `os.fsencode` maps back to the original byte, so `api.run` hands
    the string to `history.resolve`, `git rev-parse` receives the bytes that were typed, and git
    refnames permit any byte at or above `0x80` - so a repository can genuinely hold the ref, git
    resolves it, and the surrogate rides into the record. A surrogate outside that range cannot
    come off a command line at all: `os.fsencode` refuses it, and the subprocess never starts.

    **What "never starts" used to mean was a traceback**, which is why `api.run` now checks the ref
    it was handed before it resolves one. `base_sha=await services.history.resolve(ref)` is written
    as an argument to `RunSpec(...)`, and a constructor's arguments are evaluated before its body -
    so this check sat *behind* the git call rather than in front of it, and an out-of-range
    surrogate reached `create_subprocess_exec` first and came back as a bare `UnicodeEncodeError`.
    Not from a command line, but `api.run` takes `base_ref=` from Python and `src/agl/testing.py`
    passes one through. That ordering is `tests/test_api.py`'s claim, `adapters/git/_runner.py` is
    where the encode failure is now translated, and this line is what both of them call.

    **`workflow` and `workflow_version` are deliberately not checked, and this is where that is
    written down** so it is not re-proposed as an oversight. `workflow` is whatever
    `registry.load` matched against the installed entry points, and an unmatched name is a
    `NotFoundError` before any record exists; entry point names are read from package metadata as
    UTF-8 and cannot carry one. `workflow_version` is a literal in a workflow author's own source,
    which is code being installed rather than input arriving. Neither reaches this field from
    outside, and a check that cannot fire is a claim nobody can maintain.
    """
    for surrogate in ("\udcff", "weird\udcffname", "\ud800", "refs/heads/\udc80"):
        with pytest.raises(InputError, match="surrogate") as given:
            replace(_SPEC, base_ref=surrogate)
        assert exit_code_for(given.value) == 2, _WRONG_EXIT

    with pytest.raises(InputError, match="surrogate") as read_back:
        RunSpec.from_json({**_WIRE, "base_ref": "weird\udcffname"})
    assert exit_code_for(read_back.value) == 2, _WRONG_EXIT

    for spelled in ("main", "refs/heads/main", "v1.0.0^{commit}", "caf\u00e9", "\U0001f34c", "a b"):
        assert replace(_SPEC, base_ref=spelled).base_ref == spelled, (
            "a ref git is perfectly happy with was refused. The rule here is category Cs and "
            "nothing else - what a ref may be spelled like is git's to say, not this module's"
        )
    landed = json.loads(json.dumps(replace(_SPEC, base_ref="caf\u00e9").to_json()))
    assert landed["base_ref"] == "caf\u00e9", "the field must survive the encoder it is refused for"


# --- The pin ------------------------------------------------------------------------------------


def test_the_pin_is_a_full_object_id_and_a_printed_abbreviation_is_not_one() -> None:
    """An abbreviation is unique when printed and stops being unique as the repository grows. The
    example record this suite is built from prints twenty characters, which this module reads as
    elision for the page. Stated as a test so the disagreement is on the record."""
    assert replace(_SPEC, base_sha=_SHA).base_sha == _SHA
    assert replace(_SPEC, base_sha=_SHA256).base_sha == _SHA256
    with pytest.raises(InternalError, match="not a resolved commit"):
        replace(_SPEC, base_sha=_ABBREVIATED)


@pytest.mark.parametrize(
    "sha",
    [
        "", "a" * 39, "a" * 41, "a" * 63, "a" * 65, _SHA.upper(), "g" * 40, "a" * 39 + "-",
        _SHA + " ", "\uff18" + _SHA[1:], _SHA[:-1] + "\u0430",
    ],
)  # fmt: skip
def test_a_sha_that_is_not_a_full_lowercase_object_id_is_refused(sha: str) -> None:
    """Lowercase too: two spellings of one commit are two strings, and a resume compares them."""
    with pytest.raises(InternalError, match="not a resolved commit"):
        replace(_SPEC, base_sha=sha)


# --- The timestamp ------------------------------------------------------------------------------


def test_the_timestamp_is_one_instant_in_utc_held_to_whole_seconds() -> None:
    """Any aware spelling is accepted and normalised; `Z` at second precision is what is written."""
    berlin = datetime(2026, 8, 18, 11, 14, 2, tzinfo=timezone(timedelta(hours=2)))
    assert replace(_SPEC, created_at=berlin) == _SPEC
    assert replace(_SPEC, created_at=berlin).to_json()["created_at"] == "2026-08-18T09:14:02Z"
    assert RunSpec.from_json({**_WIRE, "created_at": "2026-08-18T11:14:02+02:00"}) == _SPEC

    fine = datetime(2026, 8, 18, 9, 14, 2, 987654, tzinfo=UTC)
    assert replace(_SPEC, created_at=fine) == _SPEC, "a field cannot hold more than it stores"
    assert RunSpec.from_json({**_WIRE, "created_at": "2026-08-18T09:14:02.987654Z"}) == _SPEC


def test_a_naive_timestamp_is_refused_rather_than_read_in_local_time() -> None:
    """A wall-clock reading with no place is not a moment, and `astimezone` would guess one."""
    with pytest.raises(InternalError, match="no timezone"):
        replace(_SPEC, created_at=datetime(2026, 8, 18, 9, 14, 2))
    with pytest.raises(InternalError):
        RunSpec.from_json({**_WIRE, "created_at": "2026-08-18T09:14:02"})


# --- Everything a record is not -----------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        None, 42, "a record", [], {}, list(_WIRE.items()),
        {key: value for key, value in _WIRE.items() if key != "workflow"},
        {key: value for key, value in _WIRE.items() if key != "params"},
    ],
)  # fmt: skip
def test_a_record_is_an_object_carrying_exactly_these_keys(payload: object) -> None:
    """`InternalError` for all of it - see the module docstring for why nothing here is exit 2."""
    with pytest.raises(InternalError):
        RunSpec.from_json(payload)


@pytest.mark.parametrize(
    "key, value",
    [
        ("workflow", 4), ("workflow", ""), ("workflow", None),
        ("workflow_version", 1.0), ("workflow_version", ""),
        ("label", ""), ("label", "agl/auth"), ("label", ".hidden"), ("label", 7),
        ("base_ref", ""), ("base_ref", ["main"]),
        ("base_sha", _ABBREVIATED), ("base_sha", None),
        ("branch", ""), ("branch", {"name": "agl/auth"}),
        ("params", None), ("params", []), ("params", "request=add oauth"),
        ("created_at", "yesterday"), ("created_at", ""), ("created_at", "2026-08-18"),
        ("created_at", 1755508442),
    ],
)  # fmt: skip
def test_a_field_that_is_not_what_the_schema_says_is_refused(key: str, value: JsonValue) -> None:
    """Wrong type, empty string, unusable label, abbreviated sha, timestamp that is not one."""
    with pytest.raises(InternalError):
        RunSpec.from_json({**_WIRE, key: value})


def test_a_record_written_by_another_version_of_agl_is_refused_rather_than_migrated() -> None:
    """The version is stamped and compared, never upgraded, and an unknown key is that rule too."""
    with pytest.raises(InternalError, match="another version"):
        RunSpec.from_json({**_WIRE, "status": "running"})
    with pytest.raises(InternalError, match="unexpected"):
        RunSpec.from_json({**_WIRE, "targets": []})
    assert replace(_SPEC, workflow_version="2.0.0") != _SPEC, "the stamp is part of the record"


def test_a_labels_own_refusal_is_re_spoken_as_ours() -> None:
    """`ids.py` says `InputError`, which is exit 2 - and nobody typed the contents of this file."""
    with pytest.raises(InternalError) as caught:
        RunSpec.from_json({**_WIRE, "label": "a b"})
    assert "cannot read back" in str(caught.value)
    assert caught.value.__cause__ is not None, "the rule actually broken stays in the traceback"
    assert "run label" in str(caught.value.__cause__)


def test_a_record_is_frozen() -> None:
    """Validated once on the way in is worth nothing if the value can be edited afterwards."""
    with pytest.raises(FrozenInstanceError):
        _SPEC.base_sha = "0" * 40  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        _SPEC.params = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        hash(_SPEC)  # a record holds params, and no dict is hashable: it is a value, not a key


# --- What this module is not allowed to be ------------------------------------------------------


def test_there_is_no_run_status() -> None:
    """`ARCHITECTURE.md`'s "Deliberately not built" refuses one by name, and the module docstring
    argues the absence out. Pinned as a test rather than left to prose because an empty enum is the
    easy thing to add here, and adding it is one field away from storing it in `run.json` - a
    second source of truth that nothing updates.

    **`checked_text` is on that list and is not a type.** It is the surrogate rule this module
    already applies to `base_ref`, made callable so that `api.run` can apply it to the *same value*
    before handing it to `History.resolve` - a constructor's arguments are all evaluated before its
    body, so the check in `__post_init__` sat behind the git call it was written to precede. One
    implementation with two call sites rather than a second spelling of the rule in `api.py`, which
    is the copy that would be free to be wrong. `tests/test_api.py` holds the ordering claim."""
    assert not hasattr(run, "RunStatus")
    assert run.__all__ == ["JsonValue", "RunSpec", "checked_text"]
    assert "status" not in run._WIRE_KEYS


def test_the_module_never_opens_the_file_it_describes() -> None:
    """It defines `run.json`'s shape and does not import `json`, know a path, or touch a disk. Read
    off the parsed source, so prose may name what the code may not. `home_layout` is absent for the
    same reason: where a record lives is `Store`'s business, not the record type's. `unicodedata`
    is a table and not a world - `ids.py` reads the same one, and `_corpus.PURE_IMPORTS` already
    counts it among what a pure module may import."""
    allowed = {"collections.abc", "dataclasses", "datetime", "math", "types", "typing"}
    allowed |= {"unicodedata", "agl.ports.errors", "agl.ports.ids"}
    assert impurities(run) == set()
    assert imported_modules(run) <= allowed
    assert "json" not in imported_modules(run)
