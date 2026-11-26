"""Tests for the (UNVERIFIED) calendar event payload builder."""

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


def test_shape_marked_unverified(event_payload):
    assert event_payload.PAYLOAD_SHAPE_VERIFIED is False
