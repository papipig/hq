from __future__ import annotations

import pygame

from dungeon import DungeonMap

dungeon_map = DungeonMap.load()

GRID_COLS = dungeon_map.grid.cols
GRID_ROWS = dungeon_map.grid.rows
SOURCE_GRID_X = dungeon_map.grid.origin_x
SOURCE_GRID_Y = dungeon_map.grid.origin_y
SOURCE_CELL_SIZE = dungeon_map.grid.cell_size
HOVER_HIGHLIGHT_COLOR = (255, 215, 120)
HOVER_HIGHLIGHT_WIDTH = 1


class Board:
    """Render a calibrated 26x19 board with resolution-independent square cells."""

    def __init__(self, screen: pygame.Surface, left_offset: int = 0) -> None:
        self.screen = screen
        self.area_rect = pygame.Rect(0, 0, 0, 0)
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.cell_size = 0
        self.scale = 1.0
        self.image_rect = pygame.Rect(0, 0, 0, 0)
        self._surface: pygame.Surface | None = None
        self._left_offset = max(0, left_offset)
        self.resize(screen.get_size())

    def resize(self, screen_size: tuple[int, int]) -> None:
        ww, wh = screen_size
        available = pygame.Rect(self._left_offset, 0, max(1, ww - self._left_offset), max(1, wh))
        self.area_rect = available

        # Keep perfect squares: one shared cell size for both axes.
        self.cell_size = max(1, min(available.width // GRID_COLS, available.height // GRID_ROWS))
        board_w = self.cell_size * GRID_COLS
        board_h = self.cell_size * GRID_ROWS

        # Center the board inside available area to absorb odd resolutions.
        x = available.x + (available.width - board_w) // 2
        y = available.y + (available.height - board_h) // 2
        self.rect = pygame.Rect(x, y, board_w, board_h)
        self.scale = self.cell_size / SOURCE_CELL_SIZE
        self.load()

    def load(self) -> None:
        if not dungeon_map.tile.exists():
            # Placeholder: dark board with visible 26x19 grid.
            surf = pygame.Surface(self.rect.size)
            surf.fill((30, 25, 20))
            for col in range(GRID_COLS + 1):
                x = col * self.cell_size
                pygame.draw.line(surf, (50, 45, 40), (x, 0), (x, self.rect.height))
            for row in range(GRID_ROWS + 1):
                y = row * self.cell_size
                pygame.draw.line(surf, (50, 45, 40), (0, y), (self.rect.width, y))
            self._surface = surf
            self.image_rect = self.rect.copy()
            return

        raw = pygame.image.load(str(dungeon_map.tile)).convert()
        raw_w, raw_h = raw.get_size()
        scaled_w = max(1, int(raw_w * self.scale))
        scaled_h = max(1, int(raw_h * self.scale))
        self._surface = pygame.transform.smoothscale(raw, (scaled_w, scaled_h))
        self.image_rect = pygame.Rect(
            self.rect.x - int(SOURCE_GRID_X * self.scale),
            self.rect.y - int(SOURCE_GRID_Y * self.scale),
            scaled_w,
            scaled_h,
        )

    def cell_to_px(self, col: int, row: int) -> tuple[int, int]:
        """Top-left pixel of a logical cell."""
        return (
            self.rect.x + col * self.cell_size,
            self.rect.y + row * self.cell_size,
        )

    def px_to_cell(self, px: int, py: int) -> tuple[int, int] | None:
        """Convert pixel coordinates to (col, row), or None outside board."""
        if not self.rect.collidepoint(px, py):
            return None
        col = (px - self.rect.x) // self.cell_size
        row = (py - self.rect.y) // self.cell_size
        return int(col), int(row)

    def cell_rect(self, col: int, row: int) -> pygame.Rect:
        x, y = self.cell_to_px(col, row)
        return pygame.Rect(x, y, self.cell_size, self.cell_size)

    def draw(self) -> None:
        if self._surface:
            previous_clip = self.screen.get_clip()
            self.screen.set_clip(self.area_rect)
            self.screen.blit(self._surface, self.image_rect)
            self.screen.set_clip(previous_clip)

    def draw_hover_cell(self, mouse_pos: tuple[int, int]) -> None:
        """Debug helper: highlight hovered cell to validate mapping."""
        cell = self.px_to_cell(*mouse_pos)
        if cell is None:
            return
        col, row = cell
        rect = self.cell_rect(col, row)
        pygame.draw.rect(self.screen, HOVER_HIGHLIGHT_COLOR, rect, HOVER_HIGHLIGHT_WIDTH)

    def draw_debug_walls(self) -> None:
        """Draw red wall segments from dungeon internal wall data."""
        color = (240, 30, 30)
        thickness = 3

        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                rect = self.cell_rect(col, row)

                if dungeon_map.has_wall(col, row, "N"):
                    pygame.draw.line(self.screen, color, rect.topleft, rect.topright, thickness)
                if dungeon_map.has_wall(col, row, "W"):
                    pygame.draw.line(self.screen, color, rect.topleft, rect.bottomleft, thickness)
                if col == GRID_COLS - 1 and dungeon_map.has_wall(col, row, "E"):
                    pygame.draw.line(self.screen, color, rect.topright, rect.bottomright, thickness)
                if row == GRID_ROWS - 1 and dungeon_map.has_wall(col, row, "S"):
                    pygame.draw.line(self.screen, color, rect.bottomleft, rect.bottomright, thickness)
