"""Tests for the calendar event payload builder."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest


def test_timed_event_payload(event_payload):
    body = event_payload.build_event_payload(
        summary="Practice",
        start=datetime(2026, 1, 1, 16, tzinfo=UTC),
        end=datetime(2026, 1, 1, 17, tzinfo=UTC),
        category_ids=["111"],
        timezone="UTC",
    )
    assert body == {
        "summary": "Practice",
        "starts_at": "2026-01-01T16:00:00+00:00",
        "ends_at": "2026-01-01T17:00:00+00:00",
        "all_day": False,
        "kind": "standard",
        "category_ids": ["111"],
        "timezone": "UTC",
    }


def test_all_day_payload(event_payload):
    body = event_payload.build_event_payload(
        summary="Holiday",
        start=date(2026, 1, 1),
        end=date(2026, 1, 2),
        category_ids=[111],
        description="Day off",
    )
    assert body["all_day"] is True
    assert body["starts_at"] == "2026-01-01"
    assert body["category_ids"] == ["111"]
    assert body["description"] == "Day off"


def test_mixed_types_rejected(event_payload):
    with pytest.raises(ValueError):
        event_payload.build_event_payload(
            summary="x",
            start=date(2026, 1, 1),
            end=datetime(2026, 1, 2, tzinfo=UTC),
            category_ids=["1"],
        )


def test_end_before_start_rejected(event_payload):
    with pytest.raises(ValueError):
        event_payload.build_event_payload(
            summary="x", start=date(2026, 1, 2), end=date(2026, 1, 1), category_ids=["1"]
        )


def test_shape_marked_verified(event_payload):
    assert event_payload.PAYLOAD_SHAPE_VERIFIED is True


def test_all_day_end_converted_to_inclusive(event_payload):
    body = event_payload.build_event_payload(
        summary="Trip", start=date(2026, 1, 1), end=date(2026, 1, 4), category_ids=["1"]
    )
    assert (body["starts_at"], body["ends_at"]) == ("2026-01-01", "2026-01-03")


def test_single_all_day_has_equal_start_and_end(event_payload):
    for end in (date(2026, 1, 1), date(2026, 1, 2)):
        body = event_payload.build_event_payload(
            summary="Day", start=date(2026, 1, 1), end=end, category_ids=["1"]
        )
        assert body["starts_at"] == body["ends_at"] == "2026-01-01"


def test_naive_datetime_rejected(event_payload):
    with pytest.raises(ValueError, match="timezone-aware"):
        event_payload.build_event_payload(
            summary="x",
            start=datetime(2026, 1, 1, 7, 10),
            end=datetime(2026, 1, 1, 8),
            category_ids=["1"],
        )
