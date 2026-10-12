"""What Equinox compared for a pair, and why, in words (feat-14, D99).

The matcher compares two markets' terms field by field: the event, the outcome, who decides it,
the date. Its key ("coventry city vs newcastle united|full_time_score_2_1|official_match_score|
2026-10-12|eq|1|indicator") holds exactly that, but reads as code. Here each field is a line in
words, one column per venue (or one, when they agree), with the lines that differ marked, and one
sentence on why that makes the pair the same bet or not.
"""

import re
from datetime import date
from html import escape
from string import capwords

from equinox.catalog.review import ALIKE, EXACT, MODEL, RULED, Pair
from equinox.web import words

FIELDS = ("Event", "Outcome", "Decided by", "Date")
_SCORE = re.compile(r"^(full_time|first_half)_score_(\d+)_(\d+)$")
_DIRECTIONS = {"above": "above", "below": "below", "eq": "exactly", "between": "between"}
_SHARED = re.compile(r"they share (\d+) of (\d+) words")


def panel(pair: Pair, keys: tuple[str | None, str | None]) -> str:
    """The "How it was decided" fold: what was compared, and why."""
    table = _table(pair, keys) if all(keys) else ""
    return (
        "<details><summary>How it was decided</summary>"
        f"{table}<p class='small'>{escape(why(pair, keys))}</p></details>"
    )


def read(key: str) -> dict[str, str]:
    """A terms key's fields in words: {Event, Outcome, Decided by, Date}."""
    parts = key.split("|")
    subject, measure, measured_by, observed_on = parts[:4]
    rest = parts[4:]
    instant = rest.pop(0) if rest and "T" in rest[0] else ""
    direction, threshold, unit = rest[0], rest[1], rest[-1]
    upper = rest[2] if len(rest) == 4 else ""
    stated = f" at {instant[11:16]} UTC" if instant else ""
    return {
        "Event": _named(subject),
        "Outcome": _outcome(key, subject, measure, direction, threshold, upper, unit),
        "Decided by": "Not stated" if measured_by == "unstated" else _source(measured_by),
        "Date": f"{words.day(date.fromisoformat(observed_on))}{stated}",
    }


def why(pair: Pair, keys: tuple[str | None, str | None]) -> str:
    if not all(keys):
        shared = _SHARED.search(" ".join(pair.reasons))
        share = f" (they share {shared[1]} of {shared[2]} words)" if shared else ""
        return (
            f"Neither venue's rules could be read into terms, so only the titles were compared"
            f"{share}: title score {pair.score}. Titles alone never make two markets the same "
            "bet, so it is never priced."
        )
    read_by = f"Terms read by {pair.read_by} from each venue's rules"
    return {
        EXACT: "Equinox's own reader turned each venue's rules into these terms. Every line "
        "matches, so YES pays under exactly the same conditions on both: the same bet.",
        MODEL: f"{read_by}, and Equinox checked every line against the venue's own text. Every "
        "line matches, so it is the same bet; because a model read it, the confidence is Medium "
        "at most.",
        RULED: f"{read_by}. The marked lines differ, so YES pays under different conditions: "
        "different bets, never priced.",
        ALIKE: f"{read_by}. The marked lines differ in a way the rules don't settle, so it is "
        "never priced.",
    }[pair.kind]


def _table(pair: Pair, keys: tuple[str | None, str | None]) -> str:
    sides = [read(key) for key in keys]
    same = keys[0] == keys[1]
    heads = ["Both venues"] if same else [words.venue(s.venue) for s in (pair.a, pair.b)]
    rows = []
    for field in FIELDS:
        texts = [sides[0][field]] if same else [s[field] for s in sides]
        differs = not same and texts[0] != texts[1]
        mark = " <span class='tag'>differs</span>" if differs else ""
        cells = "".join(f"<td>{escape(text)}</td>" for text in texts)
        rows.append(f"<tr{' class=differs' if differs else ''}><th>{field}{mark}</th>{cells}</tr>")
    head = "".join(f"<th>{escape(h)}</th>" for h in heads)
    body = "".join(rows)
    return (
        f"<table class='terms'><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def _named(subject: str) -> str:
    """ "coventry city vs newcastle united" -> "Coventry City vs Newcastle United"; "FOMC" stays."""
    spaced = subject.replace("_", " ")
    return capwords(spaced).replace(" Vs ", " vs ") if spaced == spaced.lower() else spaced


def _source(measured_by: str) -> str:
    named = words.MEASURED_BY.get(measured_by)
    return named or measured_by.replace("_", " ").capitalize()


def _outcome(key, subject, measure, direction, threshold, upper, unit) -> str:
    score = _SCORE.match(measure)
    if score:
        when = "after 90 minutes" if score[1] == "full_time" else "at half time"
        teams = [_named(team) for team in subject.split(" vs ")]
        if len(teams) == 2:
            return f"Score {when}: {teams[0]} {score[2]}, {teams[1]} {score[3]}"
    if measure == words.FED_CHANGE:
        return words.paid_when(key, "") or measure.replace("_", " ")
    plain = measure.replace("_", " ")
    if unit == "indicator" and direction == "eq" and threshold == "1":
        return plain
    bound = f"{threshold} to {upper}" if upper else threshold
    return f"{plain} {_DIRECTIONS.get(direction, direction)} {bound} {unit}"
