"""Guard layer for Skylight writes and audits.

Pure Python: this module must not import Home Assistant so it can be unit
tested in isolation. The integration wraps ``GuardViolation`` into
``HomeAssistantError`` at the service / entity boundary.

A Skylight frame shows every event to whoever is standing in front of it.
There is no per-viewer privacy. The guard therefore refuses any write that
looks private, and any write that would land on a profile (category) the user
has not explicitly allowlisted. An empty allowlist denies every write.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re
from typing import Any
import unicodedata

# Markers documented in the README. Matching is case-insensitive and runs on
# NFKC-normalized text with invisible format characters removed.
PRIVATE_MARKERS: tuple[str, ...] = ("[private]", "\U0001f512", "#private")

# "#private" must not match inside a longer hashtag such as "#privateer".
_HASHTAG_RE = re.compile(r"#private(?![\w-])")
_BRACKET = "[private]"
_LOCK = "\U0001f512"

# Reason codes (stable; used in attributes, events and tests).
REASON_PRIVATE_FLAG = "private_flag"
REASON_PRIVATE_MARKER = "private_marker"
REASON_ALLOWLIST_EMPTY = "allowlist_empty"
REASON_NO_CATEGORY = "no_category"
REASON_CATEGORY_NOT_ALLOWED = "category_not_allowed"

PRIVATE_REASONS = frozenset({REASON_PRIVATE_FLAG, REASON_PRIVATE_MARKER})


@dataclass(frozen=True)
class Violation:
    """One reason an event is refused or flagged."""

    code: str
    message: str


class GuardViolation(Exception):
    """Raised by ``check_event`` when a write is refused."""

    def __init__(self, violations: list[Violation]) -> None:
        self.violations = violations
        self.codes = [v.code for v in violations]
        super().__init__("; ".join(v.message for v in violations))

    @property
    def reason(self) -> str:
        """Human readable reason (all violations joined)."""
        return str(self)


def normalize_text(text: str | None) -> str:
    """Normalize text for marker matching.

    NFKC folds compatibility forms (for example full-width brackets and
    letters) to their plain equivalents, format characters (zero-width
    spaces/joiners, BOM, soft hyphen) are removed so they cannot be used to
    split a marker, and the result is casefolded.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", str(text))
    stripped = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return stripped.casefold()


def find_private_marker(*texts: str | None) -> str | None:
    """Return the first private marker found in any of ``texts``, else None."""
    for text in texts:
        norm = normalize_text(text)
        if not norm:
            continue
        if _BRACKET in norm:
            return _BRACKET
        if _LOCK in norm:
            return _LOCK
        if _HASHTAG_RE.search(norm):
            return "#private"
    return None


def _clean_ids(values: Iterable[Any] | None) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, int)):
        values = [values]
    out: list[str] = []
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s and s not in out:
            out.append(s)
    return out


def evaluate_event(
    title: str | None,
    description: str | None = None,
    categories: Iterable[Any] | None = None,
    allowlist: Iterable[Any] | None = None,
    *,
    private: bool = False,
    require_category: bool = True,
) -> list[Violation]:
    """Return every violation for an event (empty list means allowed)."""
    violations: list[Violation] = []

    if private:
        violations.append(
            Violation(
                REASON_PRIVATE_FLAG,
                "Event is flagged private; a Skylight frame shows every event to "
                "anyone in the room, so private events are never written to it.",
            )
        )

    marker = find_private_marker(title, description)
    if marker is not None:
        violations.append(
            Violation(
                REASON_PRIVATE_MARKER,
                f"Event title or description contains the private marker "
                f"'{marker}'; refusing to put it on a shared screen.",
            )
        )

    cats = _clean_ids(categories)
    allowed = set(_clean_ids(allowlist))

    if not allowed:
        violations.append(
            Violation(
                REASON_ALLOWLIST_EMPTY,
                "No profiles are allowlisted for writes. Configure the allowlist "
                "in the Skylight Guard integration options (empty means deny all).",
            )
        )
    elif not cats:
        if require_category:
            violations.append(
                Violation(
                    REASON_NO_CATEGORY,
                    "Event has no profile/category; pick an allowlisted profile or "
                    "set a default write profile in the integration options.",
                )
            )
    else:
        denied = [c for c in cats if c not in allowed]
        if denied:
            violations.append(
                Violation(
                    REASON_CATEGORY_NOT_ALLOWED,
                    "Event is assigned to profile(s) not in the allowlist: "
                    + ", ".join(denied),
                )
            )

    return violations


def check_event(
    title: str | None,
    description: str | None = None,
    categories: Iterable[Any] | None = None,
    allowlist: Iterable[Any] | None = None,
    *,
    private: bool = False,
) -> None:
    """Raise ``GuardViolation`` unless the event may be written to the frame."""
    violations = evaluate_event(
        title, description, categories, allowlist, private=private
    )
    if violations:
        raise GuardViolation(violations)


# ── Helpers for raw Skylight event payloads ───────────────────────────────


def event_category_ids(raw: Mapping[str, Any]) -> list[str]:
    """Extract category (profile) IDs from a raw JSON:API calendar event.

    Skylight side-loads ``categories`` (to-many) on calendar events; some
    payloads carry ``category`` (to-one) or flat attribute IDs instead.
    """
    ids: list[str] = []
    rels = raw.get("relationships") or {}
    many = ((rels.get("categories") or {}).get("data")) or []
    if isinstance(many, Mapping):
        many = [many]
    for item in many:
        if isinstance(item, Mapping) and item.get("id") is not None:
            ids.append(str(item["id"]))
    one = (rels.get("category") or {}).get("data")
    if isinstance(one, Mapping) and one.get("id") is not None:
        ids.append(str(one["id"]))
    attrs = raw.get("attributes") or {}
    ids.extend(_clean_ids(attrs.get("category_ids")))
    ids.extend(_clean_ids(attrs.get("category_id")))
    return _clean_ids(ids)


def event_is_flagged_private(raw: Mapping[str, Any]) -> bool:
    """Best-effort private flag on a raw event (field names are not documented)."""
    attrs = raw.get("attributes") or {}
    if attrs.get("private") is True or attrs.get("is_private") is True:
        return True
    visibility = str(attrs.get("visibility") or "").casefold()
    return visibility in {"private", "confidential"}


def parse_when(value: Any, tzinfo: Any = None) -> datetime | None:
    """Parse an ISO date or datetime string into an aware datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.min)
    else:
        text = str(value).strip()
        try:
            if len(text) == 10:
                dt = datetime.combine(date.fromisoformat(text), time.min)
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None and tzinfo is not None:
        dt = dt.replace(tzinfo=tzinfo)
    return dt


@dataclass(frozen=True)
class RogueEvent:
    """An upcoming event that breaks the guard policy."""

    event_id: str | None
    title: str
    starts_at: str | None
    reasons: tuple[str, ...]

    @property
    def is_private(self) -> bool:
        return bool(PRIVATE_REASONS.intersection(self.reasons))


def audit_events(
    raw_events: Iterable[Mapping[str, Any]],
    allowlist: Iterable[Any] | None,
    now: datetime,
    *,
    horizon_days: int = 14,
    flag_uncategorized: bool = False,
) -> list[RogueEvent]:
    """Return upcoming events (now .. now + horizon) that break the policy.

    An event is rogue when it carries a private marker or flag, or when any
    of its categories is outside the allowlist. Uncategorized events are only
    flagged when ``flag_uncategorized`` is true.
    """
    horizon = now + timedelta(days=horizon_days)
    allowed = _clean_ids(allowlist)
    out: list[RogueEvent] = []
    for raw in raw_events:
        if not isinstance(raw, Mapping):
            continue
        attrs = raw.get("attributes") or {}
        start = parse_when(attrs.get("starts_at"), now.tzinfo)
        end = parse_when(attrs.get("ends_at"), now.tzinfo) or start
        if start is None or end is None:
            continue
        if end < now or start > horizon:
            continue
        cats = event_category_ids(raw)
        codes: list[str] = []
        if event_is_flagged_private(raw):
            codes.append(REASON_PRIVATE_FLAG)
        if find_private_marker(attrs.get("summary"), attrs.get("description")):
            codes.append(REASON_PRIVATE_MARKER)
        if cats:
            # With an empty allowlist every categorized event is out of policy.
            if any(c not in allowed for c in cats):
                codes.append(REASON_CATEGORY_NOT_ALLOWED)
        elif flag_uncategorized:
            codes.append(REASON_NO_CATEGORY)
        if codes:
            out.append(
                RogueEvent(
                    event_id=str(raw["id"]) if raw.get("id") is not None else None,
                    title=str(attrs.get("summary") or ""),
                    starts_at=start.isoformat(),
                    reasons=tuple(codes),
                )
            )
    out.sort(key=lambda r: r.starts_at or "")
    return out
