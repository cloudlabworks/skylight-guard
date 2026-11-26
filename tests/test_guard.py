"""Unit tests for the pure guard layer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

ALLOW = ["111", "222"]
NOW = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def codes(guard, *args, **kwargs):
    return [v.code for v in guard.evaluate_event(*args, **kwargs)]


# ── check_event: allowed paths ────────────────────────────────────────────


def test_allowed_event_passes(guard):
    guard.check_event("Soccer practice", "Bring water", ["111"], ALLOW)


def test_multiple_allowed_categories_pass(guard):
    guard.check_event("Family dinner", None, ["111", "222"], ALLOW)


def test_integer_ids_are_normalized(guard):
    guard.check_event("Dentist", None, [111], [111, 222])


def test_word_containing_private_is_not_a_marker(guard):
    guard.check_event("Privateer museum trip", "privately funded", ["111"], ALLOW)


def test_longer_hashtag_is_not_a_marker(guard):
    guard.check_event("Film night #privateer", None, ["111"], ALLOW)


# ── private markers ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "[private] doctor",
        "[PRIVATE] doctor",
        "Doctor [Private]",
        "\U0001f512 surprise party",
        "surprise party \U0001f512",
        "Therapy #private",
        "Therapy #PRIVATE",
        "#Private: call",
    ],
)
def test_private_markers_in_title_refused(guard, title):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event(title, None, ["111"], ALLOW)
    assert exc.value.codes == [guard.REASON_PRIVATE_MARKER]


def test_private_marker_in_description_refused(guard):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event("Appointment", "details #private", ["111"], ALLOW)
    assert guard.REASON_PRIVATE_MARKER in exc.value.codes


def test_fullwidth_marker_is_normalized(guard):
    # NFKC folds full-width brackets and letters to ASCII.
    assert guard.find_private_marker("［ＰＲＩＶＡＴＥ］ note")


def test_zero_width_space_cannot_split_marker(guard):
    assert guard.find_private_marker("[pri​vate] note") == "[private]"


def test_soft_hyphen_cannot_split_hashtag(guard):
    assert guard.find_private_marker("#pri­vate") == "#private"


def test_lock_with_variation_selector(guard):
    assert guard.find_private_marker("\U0001f512️ gift") is not None


def test_turkish_dotted_capital_does_not_crash(guard):
    assert guard.find_private_marker("İstanbul trip") is None


def test_none_and_empty_text(guard):
    assert guard.find_private_marker(None, "") is None
    assert guard.normalize_text(None) == ""


# ── private flag ──────────────────────────────────────────────────────────


def test_private_flag_refused_even_if_allowlisted(guard):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event("Lunch", None, ["111"], ALLOW, private=True)
    assert exc.value.codes == [guard.REASON_PRIVATE_FLAG]


# ── allowlist ─────────────────────────────────────────────────────────────


def test_empty_allowlist_denies_all(guard):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event("Harmless", None, ["111"], [])
    assert exc.value.codes == [guard.REASON_ALLOWLIST_EMPTY]


def test_none_allowlist_denies_all(guard):
    with pytest.raises(guard.GuardViolation):
        guard.check_event("Harmless", None, ["111"], None)


def test_category_not_in_allowlist_refused(guard):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event("Harmless", None, ["999"], ALLOW)
    assert exc.value.codes == [guard.REASON_CATEGORY_NOT_ALLOWED]
    assert "999" in exc.value.reason


def test_mixed_categories_refused(guard):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event("Harmless", None, ["111", "999"], ALLOW)
    assert "999" in str(exc.value) and "111" not in str(exc.value)


def test_missing_category_refused(guard):
    with pytest.raises(guard.GuardViolation) as exc:
        guard.check_event("Harmless", None, [], ALLOW)
    assert exc.value.codes == [guard.REASON_NO_CATEGORY]


def test_blank_category_values_ignored(guard):
    assert codes(guard, "Harmless", None, ["", "  ", None], ALLOW) == [guard.REASON_NO_CATEGORY]


def test_single_string_category(guard):
    guard.check_event("Harmless", None, "111", ALLOW)


def test_multiple_violations_reported_together(guard):
    found = codes(guard, "[private] x", None, ["999"], ALLOW, private=True)
    assert found == [
        guard.REASON_PRIVATE_FLAG,
        guard.REASON_PRIVATE_MARKER,
        guard.REASON_CATEGORY_NOT_ALLOWED,
    ]


def test_require_category_false_allows_uncategorized(guard):
    assert codes(guard, "x", None, [], ALLOW, require_category=False) == []


# ── raw payload helpers ───────────────────────────────────────────────────


def test_event_category_ids_from_relationships(guard):
    raw = {
        "id": "1",
        "attributes": {"category_ids": [333]},
        "relationships": {
            "categories": {"data": [{"id": "111", "type": "category"}]},
            "category": {"data": {"id": "222", "type": "category"}},
        },
    }
    assert guard.event_category_ids(raw) == ["111", "222", "333"]


def test_event_flagged_private(guard):
    assert guard.event_is_flagged_private({"attributes": {"private": True}})
    assert guard.event_is_flagged_private({"attributes": {"visibility": "Private"}})
    assert not guard.event_is_flagged_private({"attributes": {}})


# ── audit ─────────────────────────────────────────────────────────────────


def _ev(eid, title, start, cats=(), **attrs):
    return {
        "id": eid,
        "attributes": {
            "summary": title,
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            **attrs,
        },
        "relationships": {"categories": {"data": [{"id": c} for c in cats]}},
    }


def test_audit_flags_private_and_foreign_events(guard):
    events = [
        _ev("1", "Practice", NOW + timedelta(days=1), ["111"]),
        _ev("2", "\U0001f512 gift shopping", NOW + timedelta(days=2), ["111"]),
        _ev("3", "Someone else's thing", NOW + timedelta(days=3), ["999"]),
        _ev("4", "Too far out", NOW + timedelta(days=30), ["999"]),
        _ev("5", "Already over", NOW - timedelta(days=2), ["999"]),
    ]
    rogue = guard.audit_events(events, ALLOW, NOW, horizon_days=14)
    assert [r.event_id for r in rogue] == ["2", "3"]
    assert rogue[0].is_private and not rogue[1].is_private
    assert rogue[1].reasons == (guard.REASON_CATEGORY_NOT_ALLOWED,)


def test_audit_uncategorized_only_when_enabled(guard):
    events = [_ev("1", "Synced event", NOW + timedelta(hours=2))]
    assert guard.audit_events(events, ALLOW, NOW) == []
    rogue = guard.audit_events(events, ALLOW, NOW, flag_uncategorized=True)
    assert rogue[0].reasons == (guard.REASON_NO_CATEGORY,)


def test_audit_empty_allowlist_flags_categorized(guard):
    events = [_ev("1", "Practice", NOW + timedelta(days=1), ["111"])]
    rogue = guard.audit_events(events, [], NOW)
    assert rogue[0].reasons == (guard.REASON_CATEGORY_NOT_ALLOWED,)


def test_audit_all_day_date_strings(guard):
    raw = {
        "id": "9",
        "attributes": {
            "summary": "[private] day off",
            "starts_at": "2026-01-11",
            "ends_at": "2026-01-12",
        },
    }
    rogue = guard.audit_events([raw], ALLOW, NOW)
    assert [r.event_id for r in rogue] == ["9"]


def test_audit_skips_unparseable(guard):
    raw = {"id": "x", "attributes": {"summary": "[private]", "starts_at": "not a date"}}
    assert guard.audit_events([raw, "junk"], ALLOW, NOW) == []
