"""Supplemental offset cases; real QML keyboard continuity is tested separately."""

import pytest

from app.ui.observation_text_selection import remap_observation_selection


@pytest.mark.parametrize("previous,current,anchor,position,expected", [
    ("", "first observation", 0, 0, [0, 0]),
    ("old", "new observation", 3, 3, [15, 15]),
    ("A\nkept\nB", "AA\nkept\nBBB", 2, 6, [3, 7]),
    ("A\nkept\nB", "AA\nkept\nBBB", 6, 2, [7, 3]),
    ("A\nkept\nB", "A\nB", 2, 6, [2, 2]),
    ("A\n\U0001f7e2状态\nB", "AA\n\U0001f7e2状态\nBBB", 2, 6, [3, 7]),
    ("old", "", 0, 3, [0, 0]),
])
def test_selection_tracks_surviving_utf16_content(previous, current, anchor, position, expected):
    assert remap_observation_selection(previous, current, anchor, position) == expected
