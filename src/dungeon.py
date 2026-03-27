from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
import json
import pathlib


class CellKind(StrEnum):
    VOID = "void"
    FLOOR = "floor"
    ROOM = "room"
    CORRIDOR = "corridor"
    BLOCKED = "blocked"


class EdgeKind(StrEnum):
    WALL = "wall"
    OPEN = "open"
    DOORWAY = "doorway"
    SECRET_DOOR = "secret_door"


DIRS = ("N", "E", "S", "W")
OPPOSITE_DIR = {"N": "S", "E": "W", "S": "N", "W": "E"}
DIR_OFFSETS = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}


class WallBit(IntEnum):
    LEFT = 1
    UP = 2
    RIGHT = 4
    DOWN = 8

SRC_DIR = pathlib.Path(__file__).parent
DEFAULT_DUNGEON_FILE = SRC_DIR.parent / "data" / "maps" / "dungeon.json"


@dataclass(slots=True)
class GridCalibration:
    cols: int
    rows: int
    origin_x: float
    origin_y: float
    cell_size: float


@dataclass(slots=True)
class CellData:
    kind: CellKind
    room_id: str | None = None


@dataclass(slots=True)
class DungeonMap:
    name: str
    tile: pathlib.Path
    grid: GridCalibration
    default_cell_kind: CellKind
    default_edge_kind: EdgeKind
    cells: dict[tuple[int, int], CellData]
    edges: dict[tuple[int, int, str], EdgeKind]
    rooms: dict[str, list[tuple[int, int]]]
    walls: list[list[int]]

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> "DungeonMap":
        file_path = path or DEFAULT_DUNGEON_FILE
        with file_path.open() as file:
            payload = json.load(file)

        grid_payload = payload["grid"]
        grid = GridCalibration(
            cols=int(grid_payload["cols"]),
            rows=int(grid_payload["rows"]),
            origin_x=float(grid_payload["origin"][0]),
            origin_y=float(grid_payload["origin"][1]),
            cell_size=float(grid_payload["cell_size"]),
        )

        defaults = payload.get("defaults", {})
        default_cell_kind = CellKind(defaults.get("cell_kind", CellKind.FLOOR))
        default_edge_kind = EdgeKind(defaults.get("edge_kind", EdgeKind.WALL))

        tile = (file_path.parent.parent.parent / payload["tile"]).resolve()

        walls_payload = payload.get("walls")
        if walls_payload is None:
            raise ValueError("dungeon.json must contain a 'walls' 26x19 matrix")

        if len(walls_payload) != grid.rows:
            raise ValueError(f"Expected {grid.rows} wall rows, got {len(walls_payload)}")
        for row_idx, row_values in enumerate(walls_payload):
            if len(row_values) != grid.cols:
                raise ValueError(f"Expected {grid.cols} wall columns on row {row_idx}, got {len(row_values)}")

        walls: list[list[int]] = [
            [int(cell) for cell in row_values]
            for row_values in walls_payload
        ]

        # Keep compatibility fields for code that still references cell/edge APIs.
        rooms: dict[str, list[tuple[int, int]]] = {}
        cells: dict[tuple[int, int], CellData] = {}
        edges: dict[tuple[int, int, str], EdgeKind] = {}

        return cls(
            name=str(payload.get("name", file_path.stem)),
            tile=tile,
            grid=grid,
            default_cell_kind=default_cell_kind,
            default_edge_kind=default_edge_kind,
            cells=cells,
            edges=edges,
            rooms=rooms,
            walls=walls,
        )

    def in_bounds(self, col: int, row: int) -> bool:
        return 0 <= col < self.grid.cols and 0 <= row < self.grid.rows

    def cell_data(self, col: int, row: int) -> CellData:
        if not self.in_bounds(col, row):
            raise IndexError(f"Cell out of bounds: {(col, row)}")
        return self.cells.get((col, row), CellData(kind=self.default_cell_kind))

    def cell_kind(self, col: int, row: int) -> CellKind:
        return self.cell_data(col, row).kind

    def room_id(self, col: int, row: int) -> str | None:
        return self.cell_data(col, row).room_id

    def edge_kind(self, col: int, row: int, direction: str) -> EdgeKind:
        direction = direction.upper()
        if direction not in DIRS:
            raise ValueError(f"Unsupported direction: {direction}")
        if self.has_wall(col, row, direction):
            return EdgeKind.WALL
        return EdgeKind.OPEN

    def wall_mask(self, col: int, row: int) -> int:
        if not self.in_bounds(col, row):
            return 0
        return self.walls[row][col]

    def has_wall(self, col: int, row: int, direction: str) -> bool:
        if not self.in_bounds(col, row):
            return True

        direction = direction.upper()
        if direction not in DIRS:
            raise ValueError(f"Unsupported direction: {direction}")

        mask = self.wall_mask(col, row)
        if direction == "N":
            return bool(mask & WallBit.UP)
        if direction == "E":
            return bool(mask & WallBit.RIGHT)
        if direction == "S":
            return bool(mask & WallBit.DOWN)
        return bool(mask & WallBit.LEFT)

    def is_passable(self, col: int, row: int, direction: str) -> bool:
        direction = direction.upper()
        if direction not in DIRS:
            raise ValueError(f"Unsupported direction: {direction}")

        if self.has_wall(col, row, direction):
            return False

        delta_col, delta_row = DIR_OFFSETS[direction]
        other_col = col + delta_col
        other_row = row + delta_row
        if not self.in_bounds(other_col, other_row):
            return False

        # Also respect the opposite side wall bit on neighbor cell.
        return not self.has_wall(other_col, other_row, OPPOSITE_DIR[direction])
