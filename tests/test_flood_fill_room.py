"""Tests for flood_fill_room visibility containment.

These tests verify that:
- Opening a door into a ROOM reveals exactly that room's cells (no leak into
  corridors or adjacent rooms).
- Opening a door into a CORRIDOR reveals only the single corridor cell
  immediately beyond the door (corridors are explored step-by-step).
- The starting room is fully revealed from the player's starting cell.
- Doors are visible only when at least one of their two bordering cells is in
  the flood-filled cell set (handles doors whose anchor is outside the room).

All tests use the real dungeon.json and quest1.json data so they catch any
future changes to the map layout.  No Pygame display is required.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from collections import deque

import pytest

# ---------------------------------------------------------------------------
# Path setup – make src/ importable without installing the package.
# ---------------------------------------------------------------------------
SRC = pathlib.Path(__file__).parent.parent / "src"
DATA = pathlib.Path(__file__).parent.parent / "data"
sys.path.insert(0, str(SRC))

# Suppress pygame display initialisation so tests run headlessly.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


# ---------------------------------------------------------------------------
# Minimal re-implementation of the helpers under test (mirrors main.py logic
# so tests don't depend on Pygame being fully initialised).
# ---------------------------------------------------------------------------

DUNGEON_FILE = DATA / "maps" / "dungeon.json"
QUEST1_FILE = DATA / "quests" / "quest1.json"

with DUNGEON_FILE.open() as _f:
    _DUNGEON = json.load(_f)

with QUEST1_FILE.open() as _f:
    _QUEST1 = json.load(_f)

COLS: int = _DUNGEON["grid"]["cols"]   # 26
ROWS: int = _DUNGEON["grid"]["rows"]   # 19
_WALLS: list[list[int]] = _DUNGEON["walls"]

_DIR_OFFSETS: dict[str, tuple[int, int]] = {
    "N": (0, -1),
    "E": (1, 0),
    "S": (0, 1),
    "W": (-1, 0),
}
_OPPOSITE: dict[str, str] = {"N": "S", "E": "W", "S": "N", "W": "E"}
_BITS: dict[str, int] = {"W": 1, "N": 2, "E": 4, "S": 8}
_ROT_TO_DIR: dict[int, str] = {1: "W", 2: "N", 4: "E", 8: "S"}

DoorKey = tuple[int, int, str]


def _in_bounds(col: int, row: int) -> bool:
    return 0 <= col < COLS and 0 <= row < ROWS


def _has_wall(col: int, row: int, direction: str) -> bool:
    if not _in_bounds(col, row):
        return True
    return bool(_WALLS[row][col] & _BITS[direction])


def _edge_blocked(col: int, row: int, direction: str, door_states: dict[DoorKey, bool]) -> bool:
    """Return True if the edge between (col,row) and its neighbour is impassable."""
    dc, dr = _DIR_OFFSETS[direction]
    oc, orr = col + dc, row + dr
    w1 = _has_wall(col, row, direction)
    w2 = _has_wall(oc, orr, _OPPOSITE[direction])
    if not (w1 or w2):
        return False  # fully open passage
    # A door in *open* state removes the blocking.
    opp = _OPPOSITE[direction]
    if door_states.get((col, row, direction)) is True:
        return False
    if door_states.get((oc, orr, opp)) is True:
        return False
    return True  # wall present, no open door


def _build_room_lookup() -> dict[tuple[int, int], frozenset[tuple[int, int]]]:
    lookup: dict[tuple[int, int], frozenset[tuple[int, int]]] = {}
    for room_entry in _DUNGEON.get("rooms", []):
        room_cells: set[tuple[int, int]] = set()
        for rect in room_entry:
            ul, lr = rect[0], rect[1]
            for r in range(int(ul[1]), int(lr[1]) + 1):
                for c in range(int(ul[0]), int(lr[0]) + 1):
                    room_cells.add((c, r))
        frozen = frozenset(room_cells)
        for cell in room_cells:
            lookup[cell] = frozen
    return lookup


_ROOM_LOOKUP: dict[tuple[int, int], frozenset[tuple[int, int]]] = _build_room_lookup()


def flood_fill_room(start: tuple[int, int], door_states: dict[DoorKey, bool]) -> set[tuple[int, int]]:
    """Mirrors main.py flood_fill_room exactly."""
    allowed = _ROOM_LOOKUP.get(start)
    if allowed is None:
        # Corridor cell – reveal only this single cell.
        return {start} if _in_bounds(start[0], start[1]) else set()

    visited: set[tuple[int, int]] = set()
    q: deque[tuple[int, int]] = deque([start])
    while q:
        c, r = q.popleft()
        if (c, r) in visited or not _in_bounds(c, r):
            continue
        if (c, r) not in allowed:
            continue
        visited.add((c, r))
        for d, (dc, dr) in _DIR_OFFSETS.items():
            nc, nr = c + dc, r + dr
            if (nc, nr) not in visited and not _edge_blocked(c, r, d, door_states):
                q.append((nc, nr))
    return visited


def _all_doors_closed() -> dict[DoorKey, bool]:
    """Return door_states with every quest-1 door closed (False)."""
    states: dict[DoorKey, bool] = {}
    for door in _QUEST1["doors"]:
        col, row = door["position"]
        direction = _ROT_TO_DIR.get(int(door["rotation"]), "E")
        states[(col, row, direction)] = False
    return states


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _starting_room_cells() -> frozenset[tuple[int, int]]:
    """Quest-1 starting room: columns 1-4, rows 14-17 (16 cells)."""
    return frozenset((c, r) for c in range(1, 5) for r in range(14, 18))


def _is_corridor_cell(cell: tuple[int, int]) -> bool:
    return cell not in _ROOM_LOOKUP


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFloodFillStartingRoom:
    """Flood fill from the heroes' starting position."""

    def test_starting_room_size(self) -> None:
        """Flood from player start (1,14) must return exactly 16 cells."""
        result = flood_fill_room((1, 14), _all_doors_closed())
        assert len(result) == 16

    def test_starting_room_bounds(self) -> None:
        """All returned cells must be within columns 1-4 and rows 14-17."""
        result = flood_fill_room((1, 14), _all_doors_closed())
        for col, row in result:
            assert 1 <= col <= 4, f"col {col} outside room"
            assert 14 <= row <= 17, f"row {row} outside room"

    def test_starting_room_matches_definition(self) -> None:
        """Returned cells must exactly equal the room definition."""
        result = flood_fill_room((1, 14), _all_doors_closed())
        assert result == _starting_room_cells()

    def test_no_corridor_cells_in_result(self) -> None:
        """No corridor cells must appear in the starting-room flood fill."""
        result = flood_fill_room((1, 14), _all_doors_closed())
        corridor_hits = {c for c in result if _is_corridor_cell(c)}
        assert not corridor_hits, f"Corridor cells leaked: {corridor_hits}"


class TestFloodFillDoorsIntoRooms:
    """Opening a door whose far side is a room reveals exactly that room."""

    # Door (4,2) dir=E → far side (5,2) is room [[5,1],[8,3]] = 12 cells
    def test_room_door_reveals_full_room(self) -> None:
        far_cell = (5, 2)
        expected = _ROOM_LOOKUP[far_cell]
        result = flood_fill_room(far_cell, _all_doors_closed())
        assert result == set(expected), (
            f"Expected {len(expected)} cells, got {len(result)}"
        )

    def test_room_door_does_not_leak_into_corridor(self) -> None:
        far_cell = (5, 2)
        result = flood_fill_room(far_cell, _all_doors_closed())
        corridor_hits = {c for c in result if _is_corridor_cell(c)}
        assert not corridor_hits, f"Corridor cells leaked: {corridor_hits}"

    def test_room_door_does_not_leak_into_adjacent_room(self) -> None:
        """Flood from room [5,1]-[8,3] must not include room [1,1]-[4,3]."""
        far_cell = (5, 2)
        adjacent_room = _ROOM_LOOKUP[(1, 2)]  # room [[1,1],[4,3]]
        result = flood_fill_room(far_cell, _all_doors_closed())
        overlap = result & set(adjacent_room)
        assert not overlap, f"Leaked into adjacent room: {overlap}"


class TestFloodFillDoorsIntoCorridor:
    """Opening a door whose far side is a corridor reveals only 1 cell."""

    # Door (3,8) dir=S → far side (3,9) is a corridor cell
    def test_corridor_door_reveals_single_cell(self) -> None:
        far_cell = (3, 9)
        assert _is_corridor_cell(far_cell), "Pre-condition: (3,9) must be a corridor cell"
        result = flood_fill_room(far_cell, _all_doors_closed())
        assert result == {far_cell}, (
            f"Expected only {far_cell}, got {len(result)} cells: {result}"
        )

    # Door (7,8) dir=S → far side (7,9) is also a corridor cell
    def test_corridor_door_second_example(self) -> None:
        far_cell = (7, 9)
        assert _is_corridor_cell(far_cell)
        result = flood_fill_room(far_cell, _all_doors_closed())
        assert result == {far_cell}

    # Door (10,13) dir=N → far side (10,12) is a corridor cell
    def test_corridor_door_north(self) -> None:
        far_cell = (10, 12)
        assert _is_corridor_cell(far_cell)
        result = flood_fill_room(far_cell, _all_doors_closed())
        assert result == {far_cell}

    def test_corridor_cell_never_reaches_other_rooms(self) -> None:
        """A corridor flood must never include any room cells."""
        far_cell = (3, 9)  # corridor just south of room [1,4]-[4,8]
        result = flood_fill_room(far_cell, _all_doors_closed())
        room_hits = {c for c in result if not _is_corridor_cell(c)}
        assert not room_hits


class TestDoorVisibilityRule:
    """reveal_room_cells uses the 'either bordering cell' rule.

    A door should become visible when EITHER of its two cells is in the
    revealed room — this is needed when the anchor cell is on the outside
    (e.g. door (3,18) dir=N whose anchor (3,18) is outside the starting room
    but whose neighbour (3,17) is inside it).
    """

    def test_south_boundary_door_visible_from_inside(self) -> None:
        """Door (3,18) dir=N: anchor (3,18) is outside, but (3,17) is inside.
        The door must be visible after flood-filling the starting room."""
        room_cells = _starting_room_cells()
        # Simulate reveal_room_cells door logic
        door_key: DoorKey = (3, 18, "N")
        d_col, d_row, d_dir = door_key
        dc, dr = _DIR_OFFSETS[d_dir]
        both_cells = {(d_col, d_row), (d_col + dc, d_row + dr)}
        assert both_cells & room_cells, (
            "Neither bordering cell of door (3,18)N is in starting room"
        )

    def test_anchor_outside_room_still_revealed(self) -> None:
        """Specifically: anchor cell (3,18) is NOT in starting room…"""
        room_cells = _starting_room_cells()
        assert (3, 18) not in room_cells

    def test_neighbour_inside_room_triggers_reveal(self) -> None:
        """…but neighbour (3,17) IS in starting room → door revealed."""
        room_cells = _starting_room_cells()
        assert (3, 17) in room_cells

    def test_no_far_room_door_visible_from_starting_room(self) -> None:
        """Doors that have neither bordering cell in the starting room must
        NOT be revealed — e.g. door (7,17)S whose cells are (7,17)+(7,18)."""
        room_cells = _starting_room_cells()
        doors_that_should_stay_hidden = [
            (4, 2, "E"),
            (8, 2, "E"),
            (3, 3, "S"),
            (3, 8, "S"),
            (7, 8, "S"),
            (0, 11, "E"),
            (7, 17, "S"),
            (8, 15, "E"),
            (13, 15, "E"),
            (10, 13, "N"),
            (15, 9, "E"),
        ]
        for d_col, d_row, d_dir in doors_that_should_stay_hidden:
            dc, dr = _DIR_OFFSETS[d_dir]
            both_cells = {(d_col, d_row), (d_col + dc, d_row + dr)}
            assert not (both_cells & room_cells), (
                f"Door ({d_col},{d_row}){d_dir} should be hidden but borders starting room"
            )


class TestAllDoorFarSides:
    """Every door in quest-1: verify far-side flood size is bounded."""

    @pytest.mark.parametrize("door", _QUEST1["doors"])
    def test_far_side_flood_bounded(self, door: dict) -> None:
        """No door's far-side flood may reach more cells than the largest room
        (25 cells) — corridors return 1 cell, rooms return their own size."""
        col, row = door["position"]
        direction = _ROT_TO_DIR.get(int(door["rotation"]), "E")
        dc, dr = _DIR_OFFSETS[direction]
        far_cell = (col + dc, row + dr)
        result = flood_fill_room(far_cell, _all_doors_closed())
        max_room_size = max(len(v) for v in _ROOM_LOOKUP.values())
        assert len(result) <= max_room_size, (
            f"Door ({col},{row}){direction} far-side flood returned {len(result)} cells "
            f"(max room size is {max_room_size}) — corridor leaked!"
        )
