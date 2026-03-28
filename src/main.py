from __future__ import annotations

import argparse
import json
import pathlib
import random
from typing import TypeAlias

import pygame

import audio as audio_mod

from board import (
    Board,
    GRID_COLS,
    GRID_ROWS,
    HOVER_HIGHLIGHT_COLOR,
    HOVER_HIGHLIGHT_WIDTH,
    dungeon_map,
)
from dungeon import CellData, CellKind, DIR_OFFSETS, OPPOSITE_DIR
from objects import GameObjectDefinition, ObjectPlacement, load_object_definitions, load_object_sprite
from player import PlayerClass, load_enemies, load_player_icon, load_players

WINDOW_SIZE = (1500, 900)
BACKGROUND_COLOR = (25, 22, 18)
ACCENT_COLOR = (201, 166, 98)
TEXT_COLOR = (235, 228, 214)
PANEL_BG = (18, 15, 12)
PANEL_ROW = (42, 34, 27)
PANEL_ROW_HOVER = (62, 50, 38)
TOOLTIP_BG = (12, 10, 8)
BUTTON_BG = (72, 57, 40)
BUTTON_HOVER = (96, 76, 52)
BUTTON_DISABLED = (48, 40, 33)
PASS_BUTTON_BG = (46, 66, 98)
PASS_BUTTON_HOVER = (60, 84, 122)
PASS_BUTTON_BORDER = (150, 190, 235)
MOVE_HIGHLIGHT = (90, 220, 120, 105)
PANEL_TRANSITION_COLOR = (8, 6, 5)
PANEL_TRANSITION_MS = 220
INACTIVE_TEXT_COLOR = (150, 144, 136)

ACTIONS = [
    "ATTACK",
    "CAST SPELL",
    "SEARCH FOR TREASURE",
    "SEARCH FOR SECRET DOORS",
    "SEARCH FOR TRAPS",
    "DISARM A TRAP"
]

SRC_DIR = pathlib.Path(__file__).parent
ASSETS_DIR = SRC_DIR.parent / "assets"
SPLASH_IMAGE = ASSETS_DIR / "graphics" / "ui" / "box.jpg"
QUESTS_DIR = SRC_DIR.parent / "data" / "quests"
DEBUG_DEFAULT_QUEST = QUESTS_DIR / "quest1.json"
DOOR_MASK_TO_DIR = {1: "W", 2: "N", 4: "E", 8: "S"}
DOOR_VALID_MASK = 1 | 2 | 4 | 8
DoorKey: TypeAlias = tuple[int, int, str]
ObjectInstanceKey: TypeAlias = tuple[str, int]
MUSIC_END_EVENT = pygame.USEREVENT + 1

COMBAT_DIE_FACES = ("skull", "skull", "skull", "human_shield", "human_shield", "monster_shield")
DEATH_ANIM_MS = 2000


def door_wall_rect(board: Board, col: int, row: int, direction: str) -> pygame.Rect:
    cell_rect = board.cell_rect(col, row)
    door_length = max(8, int(round(board.cell_size * 0.72)))
    door_thickness = max(6, int(round(board.cell_size * 0.18)))
    half_thickness = door_thickness // 2

    if direction == "N":
        return pygame.Rect(cell_rect.centerx - door_length // 2, cell_rect.top - half_thickness, door_length, door_thickness)
    if direction == "S":
        return pygame.Rect(cell_rect.centerx - door_length // 2, cell_rect.bottom - half_thickness, door_length, door_thickness)
    if direction == "W":
        return pygame.Rect(cell_rect.left - half_thickness, cell_rect.centery - door_length // 2, door_thickness, door_length)
    return pygame.Rect(cell_rect.right - half_thickness, cell_rect.centery - door_length // 2, door_thickness, door_length)


def load_quest_payload(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    with path.open() as file:
        return json.load(file)


def validate_quest_objects(
    object_definitions: list[GameObjectDefinition],
    quest_payload: dict,
    quest_path: pathlib.Path,
) -> None:
    by_object_id = {definition.object_id.lower(): definition for definition in object_definitions}
    errors: list[str] = []
    for quest_object in quest_payload.get("objects", []):
        object_name = str(quest_object.get("name", "")).lower()
        if object_name not in by_object_id:
            continue
        position = quest_object.get("position")
        if not isinstance(position, list) or len(position) != 2:
            errors.append(f"  '{object_name}': missing or invalid 'position'")
            continue
        rotation = int(quest_object.get("rotation", 0))
        if rotation not in {0, 1, 2, 3}:
            errors.append(f"  '{object_name}' at {position}: rotation must be 0,1,2,3 (got {rotation})")
            continue

        definition = by_object_id[object_name]
        obj_w, obj_h = definition.size
        placed_w, placed_h = (obj_h, obj_w) if rotation % 2 else (obj_w, obj_h)
        left = int(position[0])
        top = int(position[1])
        right = left + placed_w - 1
        bottom = top + placed_h - 1
        if not dungeon_map.in_bounds(left, top) or not dungeon_map.in_bounds(right, bottom):
            errors.append(
                f"  '{object_name}' at {position} with rotation {rotation}: "
                f"footprint {placed_w}x{placed_h} out of board bounds"
            )
    if errors:
        raise SystemExit(
            f"Quest consistency error in {quest_path}:\n" + "\n".join(errors)
        )


def extract_solid_rock_cells(quest_payload: dict) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for area in quest_payload.get("solid_rock", []):
        if not isinstance(area, list) or len(area) != 2:
            continue
        upper_left, lower_right = area
        if (
            not isinstance(upper_left, list)
            or len(upper_left) != 2
            or not isinstance(lower_right, list)
            or len(lower_right) != 2
        ):
            continue
        left = int(min(upper_left[0], lower_right[0]))
        top = int(min(upper_left[1], lower_right[1]))
        right = int(max(upper_left[0], lower_right[0]))
        bottom = int(max(upper_left[1], lower_right[1]))
        for col in range(left, right + 1):
            for row in range(top, bottom + 1):
                if dungeon_map.in_bounds(col, row):
                    cells.add((col, row))
    return cells


def validate_solid_rock_areas(quest_payload: dict, quest_path: pathlib.Path) -> None:
    errors: list[str] = []
    for index, area in enumerate(quest_payload.get("solid_rock", [])):
        if not isinstance(area, list) or len(area) != 2:
            errors.append(f"  solid_rock[{index}]: expected [[x1,y1],[x2,y2]]")
            continue
        upper_left, lower_right = area
        if (
            not isinstance(upper_left, list)
            or len(upper_left) != 2
            or not isinstance(lower_right, list)
            or len(lower_right) != 2
        ):
            errors.append(f"  solid_rock[{index}]: expected [[x1,y1],[x2,y2]]")
            continue

        left = int(min(upper_left[0], lower_right[0]))
        top = int(min(upper_left[1], lower_right[1]))
        right = int(max(upper_left[0], lower_right[0]))
        bottom = int(max(upper_left[1], lower_right[1]))

        if not dungeon_map.in_bounds(left, top) or not dungeon_map.in_bounds(right, bottom):
            errors.append(
                f"  solid_rock[{index}] {area}: area out of board bounds"
            )

    if errors:
        raise SystemExit(
            f"Quest consistency error in {quest_path}:\n" + "\n".join(errors)
        )


def validate_doors(quest_payload: dict, quest_path: pathlib.Path) -> None:
    errors: list[str] = []
    for index, door in enumerate(quest_payload.get("doors", [])):
        if not isinstance(door, dict):
            errors.append(f"  doors[{index}]: expected object with position and rotation")
            continue

        position = door.get("position")
        if not isinstance(position, list) or len(position) != 2:
            errors.append(f"  doors[{index}]: missing or invalid position")
            continue

        col = int(position[0])
        row = int(position[1])
        if not dungeon_map.in_bounds(col, row):
            errors.append(f"  doors[{index}] at {position}: position out of board bounds")
            continue

        mask = int(door.get("rotation", 0))
        if mask <= 0 or (mask & ~DOOR_VALID_MASK):
            errors.append(f"  doors[{index}] at {position}: rotation mask must use only 1,2,4,8")
            continue

        for bit, direction in DOOR_MASK_TO_DIR.items():
            if not (mask & bit):
                continue
            if not dungeon_map.has_wall(col, row, direction):
                errors.append(
                    f"  doors[{index}] at {position}: no wall on {direction} side for bit {bit}"
                )

    if errors:
        raise SystemExit(
            f"Quest consistency error in {quest_path}:\n" + "\n".join(errors)
        )


def extract_door_states(
    quest_payload: dict,
) -> tuple[dict[DoorKey, bool], set[DoorKey]]:
    """Return (door_states, secret_door_keys).

    secret_door_keys contains the DoorKeys of doors that start hidden.
    They are included in door_states (closed) but not in visible_doors
    until a hero searches the room they border.
    """
    door_states: dict[DoorKey, bool] = {}
    secret_door_keys: set[DoorKey] = set()
    for door in quest_payload.get("doors", []):
        if not isinstance(door, dict):
            continue
        position = door.get("position")
        if not isinstance(position, list) or len(position) != 2:
            continue
        col = int(position[0])
        row = int(position[1])
        if not dungeon_map.in_bounds(col, row):
            continue

        mask = int(door.get("rotation", 0))
        is_hidden = bool(door.get("hidden", False))
        for bit, direction in DOOR_MASK_TO_DIR.items():
            if mask & bit:
                key: DoorKey = (col, row, direction)
                door_states[key] = False
                if is_hidden:
                    secret_door_keys.add(key)
    return door_states, secret_door_keys


def load_door_image_paths() -> tuple[pathlib.Path | None, pathlib.Path | None, pathlib.Path | None]:
    """Return (open_path, closed_path, secret_path) for door sprites."""
    objects_file = SRC_DIR.parent / "data" / "objects.json"
    if not objects_file.exists():
        return None, None, None

    with objects_file.open() as file:
        payload = json.load(file)

    def resolve_image_path(raw_path: str | None) -> pathlib.Path | None:
        if not raw_path:
            return None

        base = (SRC_DIR.parent / str(raw_path)).resolve()
        if base.exists():
            return base

        # Be forgiving when JSON extension is stale.
        for ext in (".png", ".jpg", ".tga"):
            candidate = base.with_suffix(ext)
            if candidate.exists():
                return candidate
        return base

    open_path = payload.get("door_open")
    closed_path = payload.get("door_closed")
    secret_path = payload.get("door_secret")
    resolved_open = resolve_image_path(open_path)
    resolved_closed = resolve_image_path(closed_path)
    resolved_secret = resolve_image_path(secret_path)
    return resolved_open, resolved_closed, resolved_secret


def apply_quest_object_placements(
    object_definitions: list[GameObjectDefinition],
    quest_payload: dict,
) -> None:
    by_object_id = {definition.object_id.lower(): definition for definition in object_definitions}
    for quest_object in quest_payload.get("objects", []):
        object_name = str(quest_object.get("name", "")).lower()
        position = quest_object.get("position")
        if object_name not in by_object_id or not isinstance(position, list) or len(position) != 2:
            continue
        definition = by_object_id[object_name]
        rotation = int(quest_object.get("rotation", 0)) % 4
        obj_w, obj_h = definition.size
        width, height = (obj_h, obj_w) if rotation % 2 else (obj_w, obj_h)
        col = int(position[0])
        row = int(position[1])
        definition.placements.append(ObjectPlacement(col, row, (width, height), rotation=rotation))


def assign_players_to_stairs_start(
    players: list[PlayerClass],
    object_definitions: list[GameObjectDefinition],
) -> None:
    fallback_cells = [(0, 0)]
    stairs = next((definition for definition in object_definitions if definition.object_id == "stairs"), None)
    if stairs is None or not stairs.placements:
        for index, player in enumerate(players):
            player.cell = fallback_cells[index % len(fallback_cells)]
        return

    start_placement = stairs.placements[0]
    start_col, start_row = start_placement.col, start_placement.row
    width, height = start_placement.size
    spawn_cells = [
        (start_col + col_offset, start_row + row_offset)
        for row_offset in range(height)
        for col_offset in range(width)
    ]
    if not spawn_cells:
        spawn_cells = fallback_cells

    for index, player in enumerate(players):
        player.cell = spawn_cells[index % len(spawn_cells)]


def apply_furniture_blocking_to_world(object_definitions: list[GameObjectDefinition]) -> None:
    """Mark non-passthrough furniture cells as blocked in the dungeon world matrix."""
    for definition in object_definitions:
        if definition.passthrough:
            continue
        for placement in definition.placements:
            width, height = placement.size
            for col_offset in range(width):
                for row_offset in range(height):
                    col = placement.col + col_offset
                    row = placement.row + row_offset
                    if not dungeon_map.in_bounds(col, row):
                        continue
                    existing = dungeon_map.cell_data(col, row)
                    dungeon_map.cells[(col, row)] = CellData(kind=CellKind.BLOCKED, room_id=existing.room_id)


def apply_solid_rock_blocking_to_world(cells: set[tuple[int, int]]) -> None:
    for col, row in cells:
        if not dungeon_map.in_bounds(col, row):
            continue
        existing = dungeon_map.cell_data(col, row)
        dungeon_map.cells[(col, row)] = CellData(kind=CellKind.BLOCKED, room_id=existing.room_id)


def load_die_faces(size: int, font: pygame.font.Font) -> dict[int, pygame.Surface]:
    dice_dir = ASSETS_DIR / "graphics" / "sprites"
    names = {
        1: "dice_one.jpg",
        2: "dice_two.jpg",
        3: "dice_three.jpg",
        4: "dice_four.jpg",
        5: "dice_five.jpg",
        6: "dice_six.jpg",
    }
    faces: dict[int, pygame.Surface] = {}
    for value, file_name in names.items():
        path = dice_dir / file_name
        if path.exists():
            raw = pygame.image.load(str(path))
            try:
                raw = raw.convert_alpha()
            except Exception:
                raw = raw.convert()
            # If the source has a flat corner background (jpg), remove it by
            # blitting into an SRCALPHA surface with a colorkey, preserving
            # per-pixel alpha so rotated dice don't get square corners.
            try:
                bg_color = raw.get_at((0, 0))
                tmp = pygame.Surface(raw.get_size(), pygame.SRCALPHA)
                raw.set_colorkey(bg_color)
                tmp.blit(raw, (0, 0))
                faces[value] = pygame.transform.smoothscale(tmp, (size, size)).convert_alpha()
            except Exception:
                faces[value] = pygame.transform.smoothscale(raw, (size, size)).convert()
            continue

        fallback = pygame.Surface((size, size), pygame.SRCALPHA)
        # draw a filled rounded rectangle background
        bg = pygame.Surface((size, size))
        bg.fill((236, 226, 205))
        pygame.draw.rect(bg, (80, 65, 48), bg.get_rect(), 2, border_radius=6)
        fallback.blit(bg, (0, 0))
        label = font.render(str(value), True, (40, 32, 24))
        fallback.blit(label, label.get_rect(center=fallback.get_rect().center))
        faces[value] = fallback.convert_alpha()
    return faces


def load_combat_face_sprites(size: int, font: pygame.font.Font) -> dict[str, pygame.Surface]:
    dice_dir = ASSETS_DIR / "graphics" / "sprites"
    names = {
        "skull": "dice_skull.jpg",
        "human_shield": "dice_human_shield.jpg",
        "monster_shield": "dice_monster_shield.jpg",
    }
    sprites: dict[str, pygame.Surface] = {}
    fallback_labels = {
        "skull": "S",
        "human_shield": "H",
        "monster_shield": "M",
    }

    for face, file_name in names.items():
        path = dice_dir / file_name
        if path.exists():
            # Load with alpha if possible, then remove any flat background color
            # by blitting into an SRCALPHA surface. This keeps per-pixel alpha so
            # rotated sprites don't create opaque square corners.
            raw = pygame.image.load(str(path))
            try:
                raw = raw.convert_alpha()
            except Exception:
                raw = raw.convert()
            bg_color = raw.get_at((0, 0))
            # Prepare an alpha surface and blit the image with colorkey applied
            tmp = pygame.Surface(raw.get_size(), pygame.SRCALPHA)
            raw.set_colorkey(bg_color)
            tmp.blit(raw, (0, 0))
            scaled = pygame.transform.smoothscale(tmp, (size, size)).convert_alpha()
            sprites[face] = scaled
            continue

        fallback = pygame.Surface((size, size))
        fallback.fill((236, 226, 205))
        pygame.draw.rect(fallback, (80, 65, 48), fallback.get_rect(), 2, border_radius=6)
        label = font.render(fallback_labels[face], True, (40, 32, 24))
        fallback.blit(label, label.get_rect(center=fallback.get_rect().center))
        sprites[face] = fallback

    return sprites

def _load_config(debug: bool) -> dict:
    config_path = SRC_DIR / "config.json"
    with config_path.open() as f:
        data = json.load(f)
    return data["debug"] if debug else data["release"]


def draw_heart(surface: pygame.Surface, x: int, y: int, size: int, active: bool) -> None:
    color = (198, 40, 40) if active else (95, 95, 95)
    r = size // 4
    left = (x + r, y + r)
    right = (x + size - r, y + r)
    tip = (x + size // 2, y + size)
    pygame.draw.circle(surface, color, left, r)
    pygame.draw.circle(surface, color, right, r)
    pygame.draw.polygon(surface, color, [
        (x, y + r),
        (x + size, y + r),
        tip,
    ])


def circular_icon(surface: pygame.Surface, size: int, dimmed: bool = False) -> pygame.Surface:
    scaled = pygame.transform.smoothscale(surface, (size, size)).convert_alpha()
    masked = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(masked, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
    scaled.blit(masked, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    if dimmed:
        shade = pygame.Surface((size, size), pygame.SRCALPHA)
        shade.fill((70, 70, 70, 150))
        scaled.blit(shade, (0, 0))

    return scaled


def draw_left_menu(
    screen: pygame.Surface,
    panel_rect: pygame.Rect,
    mouse_pos: tuple[int, int],
    players: list[PlayerClass],
    player_icons: dict[str, pygame.Surface],
    active_player_name: str,
    enemy_menu_rows: list[dict],
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    zargon_acting_enemy_name: str | None = None,
) -> tuple[list[str] | None, int]:
    tooltip_lines: list[str] | None = None

    pygame.draw.rect(screen, PANEL_BG, panel_rect)
    pygame.draw.line(screen, ACCENT_COLOR, panel_rect.topright, panel_rect.bottomright, 2)

    title = title_font.render("Characters", True, ACCENT_COLOR)
    screen.blit(title, (panel_rect.x + 16, panel_rect.y + 16))

    y = panel_rect.y + 64
    row_h = 72
    heart_size = 14
    # During Zargon's turn suppress the hero "TURN" badge entirely.
    zargon_turn = zargon_acting_enemy_name is not None
    for hero in players:
        is_active = (not zargon_turn) and hero.name == active_player_name
        row = pygame.Rect(panel_rect.x + 12, y, panel_rect.width - 24, row_h)
        hovered = row.collidepoint(mouse_pos)
        row_color = PANEL_ROW_HOVER if hovered and is_active else PANEL_ROW_HOVER if hovered else PANEL_ROW
        if not is_active:
            row_color = (34, 30, 26) if not hovered else (48, 42, 36)
        pygame.draw.rect(screen, row_color, row, border_radius=6)

        if is_active:
            marker = pygame.Rect(row.x + 8, row.y + 8, 10, row_h - 16)
            pygame.draw.rect(screen, ACCENT_COLOR, marker, border_radius=5)
            turn_badge = text_font.render("TURN", True, ACCENT_COLOR)
            turn_rect = turn_badge.get_rect(topright=(row.right - 10, row.y + 8))
            screen.blit(turn_badge, turn_rect)

        raw_icon = player_icons.get(hero.name)
        if raw_icon is None:
            # Fallback: create a simple colored square as icon if mapping is missing
            raw_icon = pygame.Surface((44, 44))
            raw_icon.fill(hero.color)
            player_icons[hero.name] = raw_icon
        icon = circular_icon(raw_icon, 44, dimmed=not is_active)
        icon_rect = icon.get_rect(midleft=(row.x + 32, row.y + row_h // 2))
        screen.blit(icon, icon_rect)
        pygame.draw.circle(
            screen,
            ACCENT_COLOR if is_active else (90, 86, 80),
            icon_rect.center,
            icon_rect.width // 2 + 2,
            2,
        )

        name = text_font.render(hero.name, True, TEXT_COLOR if is_active else INACTIVE_TEXT_COLOR)
        text_x = icon_rect.right + 16
        screen.blit(name, (text_x, row.y + 9))

        hp = hero.hp
        max_hp = hero.max_hp
        hearts_x = text_x
        hearts_y = row.y + 36
        for i in range(max_hp):
            draw_heart(screen, hearts_x + i * (heart_size + 4), hearts_y, heart_size, i < hp)

        if hovered:
            tooltip_lines = [
                hero.name,
                f"Attack dice: {hero.attack_dice}",
                f"Defense dice: {hero.defense_dice}",
                f"Mind: {hero.mind}",
                f"Body: {hp}/{max_hp}",
            ]

        y += row_h + 10

    enemies_title = title_font.render("Enemies", True, ACCENT_COLOR)
    screen.blit(enemies_title, (panel_rect.x + 16, y + 8))
    y += 44

    for enemy in enemy_menu_rows:
        enemy_name = str(enemy["name"])
        is_acting = zargon_turn and enemy_name == zargon_acting_enemy_name
        row = pygame.Rect(panel_rect.x + 12, y, panel_rect.width - 24, 64)
        hovered = row.collidepoint(mouse_pos)
        # Acting enemy gets a distinct highlight (reddish), like the hero TURN row.
        if is_acting:
            row_bg = (60, 22, 22)
        elif hovered:
            row_bg = PANEL_ROW_HOVER
        else:
            row_bg = PANEL_ROW
        pygame.draw.rect(screen, row_bg, row, border_radius=6)

        # Left accent bar + "TURN" badge for the acting enemy
        if is_acting:
            marker = pygame.Rect(row.x + 8, row.y + 6, 10, row.height - 12)
            pygame.draw.rect(screen, (210, 60, 60), marker, border_radius=5)
            turn_badge = text_font.render("ACT", True, (210, 60, 60))
            turn_rect = turn_badge.get_rect(topright=(row.right - 10, row.y + 8))
            screen.blit(turn_badge, turn_rect)

        icon = circular_icon(enemy["icon"], 40)
        icon_rect = icon.get_rect(midleft=(row.x + 28, row.y + row.height // 2))
        screen.blit(icon, icon_rect)
        circle_color = (210, 60, 60) if is_acting else (110, 106, 100)
        circle_width = 3 if is_acting else 2
        pygame.draw.circle(screen, circle_color, icon_rect.center, icon_rect.width // 2 + 2, circle_width)

        label = text_font.render(enemy_name, True, TEXT_COLOR)
        screen.blit(label, (icon_rect.right + 12, row.y + 7))

        hp = int(enemy.get("hp", enemy.get("max_hp", 1)))
        max_hp = int(enemy.get("max_hp", hp))
        if max_hp > 1:
            hearts_x = icon_rect.right + 12
            hearts_y = row.y + 33
            for i in range(max_hp):
                draw_heart(screen, hearts_x + i * (heart_size + 4), hearts_y, heart_size, i < hp)

        if hovered:
            tooltip_lines = [
                enemy_name,
                f"Move: {enemy.get('move', 0)}",
                f"Attack dice: {enemy.get('attack_dice', 0)}",
                f"Defense dice: {enemy.get('defense_dice', 0)}",
                f"Mind: {enemy.get('mind', 0)}",
                f"Body: {hp}/{max_hp}",
            ]

        y += 72

    return tooltip_lines, y


def draw_tooltip(
    screen: pygame.Surface,
    mouse_pos: tuple[int, int],
    lines: list[str],
    text_font: pygame.font.Font,
) -> None:
    padding = 8
    line_h = text_font.get_linesize()
    width = max(text_font.size(line)[0] for line in lines) + padding * 2
    height = line_h * len(lines) + padding * 2

    x = mouse_pos[0] + 16
    y = mouse_pos[1] + 16
    sw, sh = screen.get_size()
    if x + width > sw:
        x = sw - width - 10
    if y + height > sh:
        y = sh - height - 10

    rect = pygame.Rect(x, y, width, height)
    pygame.draw.rect(screen, TOOLTIP_BG, rect, border_radius=6)
    pygame.draw.rect(screen, ACCENT_COLOR, rect, 1, border_radius=6)

    for i, line in enumerate(lines):
        txt = text_font.render(line, True, TEXT_COLOR)
        screen.blit(txt, (x + padding, y + padding + i * line_h))


def draw_button(
    screen: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    mouse_pos: tuple[int, int],
    font: pygame.font.Font,
    enabled: bool = True,
    bg_color: tuple[int, int, int] | None = None,
    hover_bg_color: tuple[int, int, int] | None = None,
    border_color: tuple[int, int, int] = ACCENT_COLOR,
) -> None:
    hovered = enabled and rect.collidepoint(mouse_pos)
    base_bg = BUTTON_BG if bg_color is None else bg_color
    hover_bg = BUTTON_HOVER if hover_bg_color is None else hover_bg_color
    bg = hover_bg if hovered else base_bg
    if not enabled:
        bg = BUTTON_DISABLED
    pygame.draw.rect(screen, bg, rect, border_radius=8)
    pygame.draw.rect(screen, border_color, rect, 2, border_radius=8)
    text_color = TEXT_COLOR if enabled else (150, 140, 128)
    label_surface = font.render(label, True, text_color)
    screen.blit(label_surface, label_surface.get_rect(center=rect.center))


def compute_reachable_cells(
    player: PlayerClass,
    players: list[PlayerClass],
    enemies: list[dict],
    steps: int,
    max_cols: int,
    max_rows: int,
    door_states: dict[DoorKey, bool],
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], tuple[int, int]]]:
    if steps <= 0:
        return {}, {}

    hero_occupied = {other.cell for other in players if other.name != player.name}
    enemy_occupied = {
        enemy_cell
        for enemy_cell in (enemy.get("cell") for enemy in enemies)
        if isinstance(enemy_cell, tuple) and len(enemy_cell) == 2
    }
    start = player.cell
    reachable_costs: dict[tuple[int, int], int] = {}
    frontier: list[tuple[int, int, int]] = [(start[0], start[1], 0)]
    best_cost: dict[tuple[int, int], int] = {start: 0}
    previous_step: dict[tuple[int, int], tuple[int, int]] = {}

    while frontier:
        col, row, cost = frontier.pop(0)
        if cost >= steps:
            continue

        for direction, (delta_col, delta_row) in DIR_OFFSETS.items():
            target_col = col + delta_col
            target_row = row + delta_row
            target = (target_col, target_row)
            next_cost = cost + 1

            if not (0 <= target_col < max_cols and 0 <= target_row < max_rows):
                continue
            if not is_passable_with_doors(col, row, direction, door_states):
                continue

            target_kind = dungeon_map.cell_kind(target_col, target_row)
            if target_kind in {CellKind.VOID, CellKind.BLOCKED}:
                continue

            # Enemy cells are hard blockers: you cannot enter or pass through them.
            if target in enemy_occupied:
                continue

            previous = best_cost.get(target)
            if previous is not None and previous <= next_cost:
                continue

            best_cost[target] = next_cost
            previous_step[target] = (col, row)
            # Ally hero cells are traversable but not valid stopping cells.
            if target not in hero_occupied:
                reachable_costs[target] = next_cost
            frontier.append((target_col, target_row, next_cost))

    return reachable_costs, previous_step


def cells_are_attack_adjacent(
    cell_a: tuple[int, int],
    cell_b: tuple[int, int],
    door_states: dict,
) -> bool:
    """Return True when cell_a and cell_b are orthogonally adjacent with no
    wall (or only an open door) between them – i.e. a melee attack is
    possible between the two cells."""
    ca_col, ca_row = cell_a
    cb_col, cb_row = cell_b
    dc = cb_col - ca_col
    dr = cb_row - ca_row
    # Must be exactly one step in one cardinal direction.
    if abs(dc) + abs(dr) != 1:
        return False
    direction = None
    if dc == 1:
        direction = "E"
    elif dc == -1:
        direction = "W"
    elif dr == 1:
        direction = "S"
    elif dr == -1:
        direction = "N"
    if direction is None:
        return False
    return is_passable_with_doors(ca_col, ca_row, direction, door_states)


def adjacent_enemy_indexes(player_cell: tuple[int, int], enemies: list[dict], door_states: dict) -> list[int]:
    indexes: list[int] = []
    for idx, enemy in enumerate(enemies):
        # ignore enemies that are currently playing their death animation
        if enemy.get("dying"):
            continue
        cell = enemy.get("cell")
        if not isinstance(cell, tuple) or len(cell) != 2:
            continue
        if cells_are_attack_adjacent(player_cell, cell, door_states):
            indexes.append(idx)
    return indexes


def roll_combat_dice(count: int) -> list[str]:
    return [random.choice(COMBAT_DIE_FACES) for _ in range(max(0, count))]


def roll_dice_rotations(count: int) -> list[int]:
    # One angle per die. Use unique angles within a throw when possible.
    if count <= 0:
        return []
    pool = list(range(-35, 36))
    random.shuffle(pool)
    if count <= len(pool):
        return pool[:count]
    return pool + [random.randint(-35, 35) for _ in range(count - len(pool))]


def compute_attack_outcome(hero: PlayerClass, enemy: dict) -> dict:
    attack_rolls = roll_combat_dice(int(hero.attack_dice))
    defense_rolls = roll_combat_dice(int(enemy.get("defense_dice", 0)))
    skulls = sum(1 for face in attack_rolls if face == "skull")
    # Enemies defend with monster shields.
    saves = sum(1 for face in defense_rolls if face == "monster_shield")
    damage = max(0, skulls - saves)

    enemy_hp = int(enemy.get("hp", enemy.get("max_hp", 1)))
    remaining_hp = max(0, enemy_hp - damage)
    return {
        "attack_rolls": attack_rolls,
        "defense_rolls": defense_rolls,
        "skulls": skulls,
        "saves": saves,
        "damage": damage,
        "defender_hp_before": enemy_hp,
        "defender_hp_after": remaining_hp,
        "defender_dead": remaining_hp <= 0,
    }


def compute_attack_outcome_enemy(enemy: dict, hero: PlayerClass) -> dict:
    """Compute the outcome when an enemy attacks a hero.

    Enemies roll attack dice (skulls) and heroes defend with human shields.
    Returns the same shape as compute_attack_outcome so the dialog renderer
    can display it without changes.
    """
    attack_rolls = roll_combat_dice(int(enemy.get("attack_dice", 0)))
    defense_rolls = roll_combat_dice(int(hero.defense_dice))
    skulls = sum(1 for face in attack_rolls if face == "skull")
    # Heroes defend with *human* shields (helmet or shield face).
    saves = sum(1 for face in defense_rolls if face in ("human_shield",))
    damage = max(0, skulls - saves)

    hero_hp = int(hero.hp)
    remaining_hp = max(0, hero_hp - damage)
    return {
        "attack_rolls": attack_rolls,
        "defense_rolls": defense_rolls,
        "skulls": skulls,
        "saves": saves,
        "damage": damage,
        "defender_hp_before": hero_hp,
        "defender_hp_after": remaining_hp,
        "defender_dead": remaining_hp <= 0,
    }

def draw_attack_dialog(
    screen: pygame.Surface,
    dialog: dict,
    attacker: "PlayerClass | dict",
    defender: dict,
    attacker_icon: pygame.Surface,
    defender_icon: pygame.Surface,
    combat_face_sprites: dict[str, pygame.Surface],
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    board: "Board",
    auto_advance: bool = False,
) -> None:
    sw, sh = screen.get_size()
    # Small translucent veil over the board area only (leave menu visible)
    veil = pygame.Surface((sw, sh), pygame.SRCALPHA)
    veil.fill((8, 6, 5, 120))
    # Only dim the board area (use board.area_rect which covers board available area)
    # but for simplicity dim whole screen lightly so UI remains readable.
    screen.blit(veil, (0, 0))

    # Make the combat panel taller (half the window height) and position it above the board area.
    panel_w = int(board.rect.width * 0.92)
    panel_h = int(sh * 0.5)
    panel_x = board.rect.x + (board.rect.width - panel_w) // 2
    panel_y = max(8, board.rect.y - panel_h - 8)
    panel = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
    pygame.draw.rect(screen, PANEL_BG, panel, border_radius=14)
    pygame.draw.rect(screen, ACCENT_COLOR, panel, 3, border_radius=14)

    header = title_font.render("Combat", True, ACCENT_COLOR)
    screen.blit(header, header.get_rect(midtop=(panel.centerx, panel.top + 16)))

    # Two compact columns inside the panel
    inner_top = panel.top + 52
    inner_h = panel_h - 72
    left_col = pygame.Rect(panel.left + 18, inner_top, panel_w // 2 - 36, inner_h)
    right_col = pygame.Rect(panel.centerx + 18, inner_top, panel_w // 2 - 36, inner_h)
    for col_rect in (left_col, right_col):
        pygame.draw.rect(screen, PANEL_ROW, col_rect, border_radius=10)

    atk_icon = circular_icon(attacker_icon, 86)
    def_icon = circular_icon(defender_icon, 86)
    screen.blit(atk_icon, atk_icon.get_rect(midtop=(left_col.centerx, left_col.top + 12)))
    screen.blit(def_icon, def_icon.get_rect(midtop=(right_col.centerx, right_col.top + 12)))

    # Support both PlayerClass (hero) and dict (enemy) as attacker.
    if isinstance(attacker, dict):
        atk_display_name = str(attacker.get("display_name", attacker.get("name", "Enemy")))
    else:
        atk_display_name = attacker.name
    atk_name = text_font.render(atk_display_name, True, TEXT_COLOR)
    def_name = text_font.render(str(defender.get("display_name", defender.get("name", "Enemy"))), True, TEXT_COLOR)
    screen.blit(atk_name, atk_name.get_rect(midtop=(left_col.centerx, left_col.top + 106)))
    screen.blit(def_name, def_name.get_rect(midtop=(right_col.centerx, right_col.top + 106)))

    # Support both PlayerClass (hero) and dict (enemy) as attacker.
    if isinstance(attacker, dict):
        atk_attack_dice = int(attacker.get("attack_dice", 0))
        atk_defense_dice = int(attacker.get("defense_dice", 0))
        atk_hp_str = f"{int(attacker.get('hp', 1))}/{int(attacker.get('max_hp', attacker.get('hp', 1)))}"
    else:
        atk_attack_dice = attacker.attack_dice
        atk_defense_dice = attacker.defense_dice
        atk_hp_str = f"{attacker.hp}/{attacker.max_hp}"
    atk_stats = [
        f"Attack dice: {atk_attack_dice}",
        f"Defense dice: {atk_defense_dice}",
        f"Body: {atk_hp_str}",
    ]
    def_stats = [
        f"Attack dice: {int(defender.get('attack_dice', 0))}",
        f"Defense dice: {int(defender.get('defense_dice', 0))}",
        f"Body: {dialog['outcome']['defender_hp_before']}/{int(defender.get('max_hp', defender.get('hp', 1)))}",
    ]

    for idx, line in enumerate(atk_stats):
        txt = text_font.render(line, True, TEXT_COLOR)
        screen.blit(txt, (left_col.left + 18, left_col.top + 144 + idx * 28))
    for idx, line in enumerate(def_stats):
        txt = text_font.render(line, True, TEXT_COLOR)
        screen.blit(txt, (right_col.left + 18, right_col.top + 144 + idx * 28))

    # Dice sizing: make them large enough to read but fit inside the compact dialog
    base_dice_size = next(iter(combat_face_sprites.values())).get_width() if combat_face_sprites else 44
    dice_size = max(28, min(64, base_dice_size * 2))
    phase = int(dialog.get("phase", 0))
    row_step = dice_size + max(8, dice_size // 4)

    # Place dice centered vertically within each column
    atk_center_y = left_col.centery
    def_center_y = right_col.centery

    def _draw_dice_row(rolls: list[str], rotations: list[int], center_x: int, center_y: int) -> None:
        if not rolls:
            return
        first_center_x = center_x - ((len(rolls) - 1) * row_step) // 2
        for idx, face in enumerate(rolls):
            sprite = combat_face_sprites.get(face)
            if sprite is None:
                continue
            # Scale sprite to desired dice size (keep alpha)
            scaled = pygame.transform.smoothscale(sprite, (dice_size, dice_size))
            angle = rotations[idx] if idx < len(rotations) else 0
            # Rotate an alpha-preserving surface; rotation will keep corners transparent
            rotated = pygame.transform.rotate(scaled, angle)
            rect = rotated.get_rect(center=(first_center_x + idx * row_step, center_y))
            screen.blit(rotated, rect)

    if phase >= 1:
        _draw_dice_row(dialog["outcome"]["attack_rolls"], dialog["attacker_rotations"], left_col.centerx, atk_center_y)

    if phase >= 2:
        _draw_dice_row(dialog["outcome"]["defense_rolls"], dialog["defender_rotations"], right_col.centerx, def_center_y)

    if phase == 0:
        result_line = "Auto-rolling…" if auto_advance else "Click to roll attack dice"
    elif phase == 1:
        skulls = dialog['outcome']['skulls']
        if auto_advance:
            result_line = f"Enemy rolled {skulls} skull(s) — click to defend!"
        else:
            result_line = f"Attacker rolled {skulls} skull(s) — rolling defence…"
    else:
        result_line = (
            f"Skulls {dialog['outcome']['skulls']}  vs  Saves {dialog['outcome']['saves']}"
            f"  =>  Damage {dialog['outcome']['damage']}"
        )
    result_txt = text_font.render(result_line, True, ACCENT_COLOR)
    screen.blit(result_txt, result_txt.get_rect(midbottom=(panel.centerx, panel.bottom - 44)))

    if auto_advance and phase < 1:
        click_label = "Auto-rolling…"
    elif phase == 0:
        click_label = "Click to attack"
    elif phase == 1:
        click_label = "…"
    else:
        click_label = "Click to resolve" if not auto_advance else "Click to resolve"
    click_txt = text_font.render(click_label, True, TEXT_COLOR)
    screen.blit(click_txt, click_txt.get_rect(midbottom=(panel.centerx, panel.bottom - 14)))


def is_passable_with_doors(
    col: int,
    row: int,
    direction: str,
    door_states: dict[DoorKey, bool],
) -> bool:
    direction = direction.upper()
    delta_col, delta_row = DIR_OFFSETS[direction]
    other_col = col + delta_col
    other_row = row + delta_row
    if not dungeon_map.in_bounds(other_col, other_row):
        return False

    if door_states.get((col, row, direction), False):
        return True

    opposite = OPPOSITE_DIR[direction]
    if door_states.get((other_col, other_row, opposite), False):
        return True

    return dungeon_map.is_passable(col, row, direction)


def _edge_has_open_door(col: int, row: int, direction: str, door_states: dict[DoorKey, bool]) -> bool:
    if door_states.get((col, row, direction), False):
        return True
    delta_col, delta_row = DIR_OFFSETS[direction]
    other_col = col + delta_col
    other_row = row + delta_row
    opposite = OPPOSITE_DIR[direction]
    return door_states.get((other_col, other_row, opposite), False)

def _edge_blocks_sight(
    col: int,
    row: int,
    direction: str,
    door_states: dict[DoorKey, bool],
) -> bool:
    delta_col, delta_row = DIR_OFFSETS[direction]
    other_col = col + delta_col
    other_row = row + delta_row
    opposite = OPPOSITE_DIR[direction]

    wall_on_this_side = dungeon_map.has_wall(col, row, direction)
    wall_on_other_side = dungeon_map.has_wall(other_col, other_row, opposite)
    if not (wall_on_this_side or wall_on_other_side):
        return False

    return not _edge_has_open_door(col, row, direction, door_states)


def has_line_of_sight(
    origin: tuple[int, int],
    target: tuple[int, int],
    door_states: dict[DoorKey, bool],
    opaque_cells: set[tuple[int, int]],
) -> bool:
    if origin == target:
        return True
    if not dungeon_map.in_bounds(target[0], target[1]):
        return False

    x0 = origin[0] + 0.5
    y0 = origin[1] + 0.5
    x1 = target[0] + 0.5
    y1 = target[1] + 0.5
    dx = x1 - x0
    dy = y1 - y0

    col = origin[0]
    row = origin[1]
    step_col = 0 if dx == 0 else (1 if dx > 0 else -1)
    step_row = 0 if dy == 0 else (1 if dy > 0 else -1)

    inf = float("inf")
    t_delta_x = inf if dx == 0 else abs(1.0 / dx)
    t_delta_y = inf if dy == 0 else abs(1.0 / dy)
    next_grid_x = (col + 1) if step_col > 0 else col
    next_grid_y = (row + 1) if step_row > 0 else row
    t_max_x = inf if dx == 0 else abs((next_grid_x - x0) / dx)
    t_max_y = inf if dy == 0 else abs((next_grid_y - y0) / dy)

    max_iter = GRID_COLS * GRID_ROWS * 4
    for _ in range(max_iter):
        if (col, row) == target:
            return True

        if t_max_x < t_max_y:
            direction = "E" if step_col > 0 else "W"
            if _edge_blocks_sight(col, row, direction, door_states):
                return False
            col += step_col
            t_max_x += t_delta_x
        elif t_max_y < t_max_x:
            direction = "S" if step_row > 0 else "N"
            if _edge_blocks_sight(col, row, direction, door_states):
                return False
            row += step_row
            t_max_y += t_delta_y
        else:
            # Exact corner crossing touches a shared vertex.
            # Diagonal sight is allowed if at least one L-shaped path around
            # the corner is open. It is blocked only when both possible paths
            # are blocked by walls/closed doors.
            direction_x = "E" if step_col > 0 else "W"
            direction_y = "S" if step_row > 0 else "N"
            blocked_from_here_x = _edge_blocks_sight(col, row, direction_x, door_states)
            blocked_from_here_y = _edge_blocks_sight(col, row, direction_y, door_states)

            adjacent_x = (col + step_col, row)
            adjacent_y = (col, row + step_row)
            blocked_from_other_x = True
            blocked_from_other_y = True
            if dungeon_map.in_bounds(adjacent_x[0], adjacent_x[1]):
                blocked_from_other_y = _edge_blocks_sight(adjacent_x[0], adjacent_x[1], direction_y, door_states)
            if dungeon_map.in_bounds(adjacent_y[0], adjacent_y[1]):
                blocked_from_other_x = _edge_blocks_sight(adjacent_y[0], adjacent_y[1], direction_x, door_states)

            path_via_x_clear = (not blocked_from_here_x) and (not blocked_from_other_y)
            path_via_y_clear = (not blocked_from_here_y) and (not blocked_from_other_x)
            if not (path_via_x_clear or path_via_y_clear):
                return False

            col += step_col
            row += step_row
            t_max_x += t_delta_x
            t_max_y += t_delta_y

        if not dungeon_map.in_bounds(col, row):
            return False
        if (col, row) != target and (col, row) in opaque_cells:
            return False

    return False


def compute_visible_cells(
    origin: tuple[int, int],
    door_states: dict[DoorKey, bool],
    opaque_cells: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    if not dungeon_map.in_bounds(origin[0], origin[1]):
        return set()

    visible: set[tuple[int, int]] = set()
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            target = (col, row)
            if has_line_of_sight(origin, target, door_states, opaque_cells):
                visible.add(target)
    return visible


def collect_opaque_cells(
    players_all: list[PlayerClass],
    enemies: list[dict],
    exclude_player_name: str | None = None,
) -> set[tuple[int, int]]:
    blocked_cells = {
        (col, row)
        for row in range(GRID_ROWS)
        for col in range(GRID_COLS)
        if dungeon_map.cell_kind(col, row) == CellKind.BLOCKED
    }
    hero_cells = {
        p.cell
        for p in players_all
        if p.name != exclude_player_name and isinstance(p.cell, tuple) and len(p.cell) == 2
    }
    enemy_cells = {
        cell
        for cell in (enemy.get("cell") for enemy in enemies)
        if isinstance(cell, tuple) and len(cell) == 2
    }
    return blocked_cells | hero_cells | enemy_cells


def reveal_room_from_opened_door(
    opened_door: DoorKey,
    door_states: dict[DoorKey, bool],
    object_definitions: list[GameObjectDefinition],
    enemies: list[dict],
    visible_objects: set[ObjectInstanceKey],
    visible_doors: set[DoorKey],
    visible_enemies: set[int],
) -> None:
    col, row, direction = opened_door
    starts = {(col, row)}
    delta_col, delta_row = DIR_OFFSETS[direction]
    other = (col + delta_col, row + delta_row)
    if dungeon_map.in_bounds(other[0], other[1]):
        starts.add(other)

    room_cells: set[tuple[int, int]] = set()
    queue = list(starts)
    while queue:
        c, r = queue.pop(0)
        if (c, r) in room_cells or not dungeon_map.in_bounds(c, r):
            continue
        room_cells.add((c, r))
        for dir_name, (dc, dr) in DIR_OFFSETS.items():
            nc, nr = c + dc, r + dr
            if not dungeon_map.in_bounds(nc, nr):
                continue
            if _edge_blocks_sight(c, r, dir_name, door_states):
                continue
            if (nc, nr) not in room_cells:
                queue.append((nc, nr))

    for definition in object_definitions:
        for placement_index, placement in enumerate(definition.placements):
            for dx in range(placement.size[0]):
                for dy in range(placement.size[1]):
                    if (placement.col + dx, placement.row + dy) in room_cells:
                        visible_objects.add((definition.object_id, placement_index))
                        break
                else:
                    continue
                break

    # Doors are discovered by LOS adjacency in update_visibility_from_player.

    for enemy_index, enemy in enumerate(enemies):
        cell = enemy.get("cell")
        if isinstance(cell, tuple) and len(cell) == 2 and cell in room_cells:
            visible_enemies.add(enemy_index)


def update_visibility_from_player(
    player: PlayerClass,
    players_all: list[PlayerClass],
    door_states: dict[DoorKey, bool],
    object_definitions: list[GameObjectDefinition],
    enemies: list[dict],
    visible_objects: set[ObjectInstanceKey],
    visible_doors: set[DoorKey],
    visible_enemies: set[int],
    secret_door_keys: set[DoorKey] | None = None,
) -> None:
    opaque_cells = collect_opaque_cells(players_all, enemies, exclude_player_name=player.name)
    visible_cells = compute_visible_cells(player.cell, door_states, opaque_cells)

    for definition in object_definitions:
        for placement_index, placement in enumerate(definition.placements):
            footprint_visible = True
            for dx in range(placement.size[0]):
                for dy in range(placement.size[1]):
                    cell = (placement.col + dx, placement.row + dy)
                    if cell not in visible_cells:
                        footprint_visible = False
                        break
                if not footprint_visible:
                    break
            if footprint_visible:
                visible_objects.add((definition.object_id, placement_index))

    for door_key in door_states.keys():
        # Never auto-reveal hidden (secret) doors — they must be found via
        # the "Search for Secret Doors" action.
        if secret_door_keys and door_key in secret_door_keys:
            continue
        col, row, direction = door_key
        adjacent = {(col, row)}
        delta_col, delta_row = DIR_OFFSETS[direction]
        other = (col + delta_col, row + delta_row)
        if dungeon_map.in_bounds(other[0], other[1]):
            adjacent.add(other)
        if any(cell in visible_cells for cell in adjacent):
            visible_doors.add(door_key)

    for enemy_index, enemy in enumerate(enemies):
        cell = enemy.get("cell")
        if isinstance(cell, tuple) and len(cell) == 2 and cell in visible_cells:
            visible_enemies.add(enemy_index)


def draw_move_options(screen: pygame.Surface, board: Board, cells: set[tuple[int, int]]) -> None:
    if not cells:
        return
    overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    for col, row in cells:
        rect = board.cell_rect(col, row)
        pygame.draw.rect(overlay, MOVE_HIGHLIGHT, rect, border_radius=8)
    screen.blit(overlay, (0, 0))


def draw_unseen_cells_overlay(
    screen: pygame.Surface,
    board: Board,
    visible_cells: set[tuple[int, int]],
) -> None:
    overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    color = (220, 30, 30, 90)
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            if (col, row) in visible_cells:
                continue
            rect = board.cell_rect(col, row)
            pygame.draw.rect(overlay, color, rect)
    screen.blit(overlay, (0, 0))


def draw_objects_on_board(
    screen: pygame.Surface,
    board: Board,
    object_definitions: list[GameObjectDefinition],
    object_sprites: dict[tuple[str, tuple[int, int], int], pygame.Surface],
    visible_objects: set[ObjectInstanceKey],
    reveal_all: bool,
) -> None:
    for definition in object_definitions:
        for placement_index, placement in enumerate(definition.placements):
            if not reveal_all and (definition.object_id, placement_index) not in visible_objects:
                continue
            sprite = object_sprites.get((
                definition.object_id,
                placement.size,
                placement.rotation,
            ))
            if sprite is None:
                continue
            x, y = board.cell_to_px(placement.col, placement.row)
            footprint_w = placement.size[0] * board.cell_size
            footprint_h = placement.size[1] * board.cell_size
            footprint_rect = pygame.Rect(x, y, footprint_w, footprint_h)
            sprite_rect = sprite.get_rect(center=footprint_rect.center)
            screen.blit(sprite, sprite_rect)


def draw_solid_rock_overlay(
    screen: pygame.Surface,
    board: Board,
    solid_rock_cells: set[tuple[int, int]],
) -> None:
    if not solid_rock_cells:
        return

    rock_set = set(solid_rock_cells)
    overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    color = (0, 0, 0, 200)
    for col, row in solid_rock_cells:
        rect = board.cell_rect(col, row)
        pygame.draw.rect(overlay, color, rect)

    # Feather exposed edges for a softer silhouette (cheap approximation, not full blur).
    feather_alphas = (120, 70, 35)
    for col, row in rock_set:
        rect = board.cell_rect(col, row)

        if (col, row - 1) not in rock_set:
            for idx, alpha in enumerate(feather_alphas, start=1):
                y = rect.top - idx
                pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(rect.left, y, rect.width, 1))

        if (col, row + 1) not in rock_set:
            for idx, alpha in enumerate(feather_alphas, start=1):
                y = rect.bottom + idx - 1
                pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(rect.left, y, rect.width, 1))

        if (col - 1, row) not in rock_set:
            for idx, alpha in enumerate(feather_alphas, start=1):
                x = rect.left - idx
                pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(x, rect.top, 1, rect.height))

        if (col + 1, row) not in rock_set:
            for idx, alpha in enumerate(feather_alphas, start=1):
                x = rect.right + idx - 1
                pygame.draw.rect(overlay, (0, 0, 0, alpha), pygame.Rect(x, rect.top, 1, rect.height))

    screen.blit(overlay, (0, 0))


def load_door_sprites(
    door_open_path: pathlib.Path | None,
    door_closed_path: pathlib.Path | None,
    board: Board,
    door_secret_path: pathlib.Path | None = None,
) -> dict[tuple[bool | str, str], pygame.Surface]:
    sprites: dict[tuple[bool | str, str], pygame.Surface] = {}
    base_length = max(8, int(round(board.cell_size * 0.72)))
    base_thickness = max(6, int(round(board.cell_size * 0.18)))
    scale = 1.8
    door_length = max(8, int(round(base_length * scale)))
    door_thickness = max(6, int(round(base_thickness * scale)))

    def make_raw(path: pathlib.Path | None, opened: bool, secret: bool = False) -> pygame.Surface:
        if path and path.exists():
            return pygame.image.load(str(path)).convert_alpha()

        fallback = pygame.Surface((door_length, door_thickness), pygame.SRCALPHA)
        if secret:
            fill = (60, 48, 90, 240)
        else:
            fill = (175, 120, 65, 240) if opened else (120, 80, 45, 240)
        pygame.draw.rect(fallback, fill, fallback.get_rect(), border_radius=3)
        pygame.draw.rect(fallback, (20, 16, 12, 220), fallback.get_rect(), 1, border_radius=3)
        return fallback

    raw_open = make_raw(door_open_path, True)
    raw_closed = make_raw(door_closed_path, False)
    raw_secret = make_raw(door_secret_path, False, secret=True)
    # Door source art is horizontal: keep N/S horizontal, rotate E/W by 90 degrees.
    rotation_by_dir = {"N": 0, "E": -90, "S": 0, "W": 90}

    for direction in ("N", "E", "S", "W"):
        angle = rotation_by_dir[direction]
        target_size = (
            (door_length, door_thickness)
            if direction in {"N", "S"}
            else (door_thickness, door_length)
        )

        open_img = pygame.transform.rotate(raw_open, angle)
        closed_img = pygame.transform.rotate(raw_closed, angle)
        secret_img = pygame.transform.rotate(raw_secret, angle)
        sprites[(True, direction)] = pygame.transform.smoothscale(open_img, target_size)
        sprites[(False, direction)] = pygame.transform.smoothscale(closed_img, target_size)
        sprites[("secret", direction)] = pygame.transform.smoothscale(secret_img, target_size)

    return sprites


def draw_doors_on_board(
    screen: pygame.Surface,
    board: Board,
    door_states: dict[DoorKey, bool],
    door_sprites: dict[tuple[bool | str, str], pygame.Surface],
    visible_doors: set[DoorKey],
    reveal_all: bool,
    secret_door_keys: set[DoorKey] | None = None,
    secret_door_reveal_times: dict[DoorKey, int] | None = None,
) -> None:
    secret_door_keys = secret_door_keys or set()
    secret_door_reveal_times = secret_door_reveal_times or {}
    now = pygame.time.get_ticks()
    SECRET_FADE_MS = 1000
    for col, row, direction in door_states:
        if not reveal_all and (col, row, direction) not in visible_doors:
            continue
        opened = door_states[(col, row, direction)]
        # Revealed-but-still-closed secret doors use the distinctive secret sprite.
        if not opened and (col, row, direction) in secret_door_keys:
            sprite_key: tuple[bool | str, str] = ("secret", direction)
        else:
            sprite_key = (opened, direction)
        sprite = door_sprites.get(sprite_key)
        if sprite is None:
            continue
        sprite_rect = door_sprite_rect(board, (col, row, direction), sprite)

        # Fade-in for newly revealed secret doors.
        reveal_time = secret_door_reveal_times.get((col, row, direction))
        if reveal_time is not None:
            elapsed = now - reveal_time
            if elapsed < SECRET_FADE_MS:
                alpha = int(255 * elapsed / SECRET_FADE_MS)
                fading = sprite.copy()
                fading.set_alpha(alpha)
                screen.blit(fading, sprite_rect)
                continue

        screen.blit(sprite, sprite_rect)


def door_sprite_rect(
    board: Board,
    door_key: DoorKey,
    sprite: pygame.Surface,
) -> pygame.Rect:
    col, row, direction = door_key
    wall_rect = door_wall_rect(board, col, row, direction)
    return sprite.get_rect(center=wall_rect.center)


def hovered_door_at_cursor(
    mouse_pos: tuple[int, int],
    board: Board,
    door_states: dict[DoorKey, bool],
    door_sprites: dict[tuple[bool, str], pygame.Surface],
    visible_doors: set[DoorKey],
    reveal_all: bool,
) -> DoorKey | None:
    for door_key, opened in door_states.items():
        if not reveal_all and door_key not in visible_doors:
            continue
        direction = door_key[2]
        sprite = door_sprites.get((opened, direction))
        if sprite is None:
            continue
        sprite_rect = door_sprite_rect(board, door_key, sprite)
        if sprite_rect.collidepoint(mouse_pos):
            return door_key
    return None


def draw_hovered_door_highlight(
    screen: pygame.Surface,
    board: Board,
    door_key: DoorKey,
    door_states: dict[DoorKey, bool],
    door_sprites: dict[tuple[bool, str], pygame.Surface],
) -> None:
    opened = door_states[door_key]
    direction = door_key[2]
    sprite = door_sprites.get((opened, direction))
    if sprite is None:
        return
    rect = door_sprite_rect(board, door_key, sprite)
    pygame.draw.rect(
        screen,
        HOVER_HIGHLIGHT_COLOR,
        rect.inflate(2, 2),
        HOVER_HIGHLIGHT_WIDTH,
        border_radius=3,
    )


def load_dungeon_rooms() -> list[list[tuple[int, int, int, int]]]:
    """Load rooms from dungeon.json.

    Each room is a list of rectangles (col_min, row_min, col_max, row_max),
    because a room can be non-rectangular (composed of several rect pieces).
    """
    data_file = SRC_DIR.parent / "data" / "maps" / "dungeon.json"
    if not data_file.exists():
        return []
    with data_file.open() as f:
        payload = json.load(f)
    rooms: list[list[tuple[int, int, int, int]]] = []
    for room_entry in payload.get("rooms", []):
        # A room entry is a list of rectangles: [[ul, lr], [ul, lr], ...]
        # But for backwards compat with a single-rect room written as [ul, lr]
        # where ul/lr are [x, y] lists, detect which form we have.
        if not isinstance(room_entry, list) or len(room_entry) == 0:
            continue
        # Single-rect shorthand: [[x1,y1],[x2,y2]]
        if isinstance(room_entry[0], list) and len(room_entry[0]) == 2 and isinstance(room_entry[0][0], (int, float)):
            ul, lr = room_entry[0], room_entry[1]
            rooms.append([(int(ul[0]), int(ul[1]), int(lr[0]), int(lr[1]))])
        else:
            # Multi-rect form: [[[x1,y1],[x2,y2]], [[x1,y1],[x2,y2]], ...]
            rects: list[tuple[int, int, int, int]] = []
            for rect in room_entry:
                if not isinstance(rect, list) or len(rect) != 2:
                    continue
                ul, lr = rect
                if not isinstance(ul, list) or not isinstance(lr, list):
                    continue
                rects.append((int(ul[0]), int(ul[1]), int(lr[0]), int(lr[1])))
            if rects:
                rooms.append(rects)
    return rooms


def get_room_indices_for_cell(
    col: int,
    row: int,
    rooms: list[list[tuple[int, int, int, int]]],
) -> set[int]:
    """Return the set of room indices that contain the given cell.

    A door sits on a wall between two cells.  To handle the case where a
    secret door is placed in the wall between two rooms (the door's cell
    belongs to room A but can also be reached from room B), we check both
    the cell itself *and* the four orthogonally adjacent cells so that a
    player standing just inside either room will detect the door.
    """
    candidates = [(col, row)]
    for dc, dr in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        candidates.append((col + dc, row + dr))

    found: set[int] = set()
    for c, r in candidates:
        for room_idx, rects in enumerate(rooms):
            for (c_min, r_min, c_max, r_max) in rects:
                if c_min <= c <= c_max and r_min <= r <= r_max:
                    found.add(room_idx)
                    break
    return found


def search_for_secret_doors(
    player: PlayerClass,
    door_states: dict[DoorKey, bool],
    secret_door_keys: set[DoorKey],
    rooms: list[list[tuple[int, int, int, int]]],
    visible_doors: set[DoorKey],
) -> list[DoorKey]:
    """Reveal hidden doors in the same room(s) as the player.

    Returns the list of newly revealed DoorKeys (empty if none found or
    player is not in any room).
    """
    if not isinstance(player.cell, tuple) or len(player.cell) != 2:
        return []

    p_col, p_row = player.cell
    player_rooms: set[int] = set()
    for room_idx, rects in enumerate(rooms):
        for (c_min, r_min, c_max, r_max) in rects:
            if c_min <= p_col <= c_max and r_min <= p_row <= r_max:
                player_rooms.add(room_idx)
                break

    if not player_rooms:
        # Player is in a corridor — no rooms to search.
        return []

    revealed: list[DoorKey] = []
    for door_key in secret_door_keys:
        if door_key in visible_doors:
            continue  # Already found
        if door_states.get(door_key, True):
            continue  # Already opened (shouldn't happen, but guard)
        d_col, d_row, _ = door_key
        door_rooms = get_room_indices_for_cell(d_col, d_row, rooms)
        if player_rooms & door_rooms:
            visible_doors.add(door_key)
            revealed.append(door_key)

    return revealed


def try_open_clicked_door(
    mouse_pos: tuple[int, int],
    board: Board,
    active_player: PlayerClass,
    door_states: dict[DoorKey, bool],
    visible_doors: set[DoorKey],
    reveal_all: bool,
) -> DoorKey | None:
    for col, row, direction in list(door_states.keys()):
        if not reveal_all and (col, row, direction) not in visible_doors:
            continue
        if door_states[(col, row, direction)]:
            continue
        wall_rect = door_wall_rect(board, col, row, direction)
        if not wall_rect.collidepoint(mouse_pos):
            continue

        adjacent = {(col, row)}
        delta_col, delta_row = DIR_OFFSETS[direction]
        other_col = col + delta_col
        other_row = row + delta_row
        if dungeon_map.in_bounds(other_col, other_row):
            adjacent.add((other_col, other_row))

        if active_player.cell in adjacent:
            door_states[(col, row, direction)] = True
            return (col, row, direction)

    return None


def reconstruct_path(
    previous_step: dict[tuple[int, int], tuple[int, int]],
    start: tuple[int, int],
    target: tuple[int, int],
) -> list[tuple[int, int]]:
    if target == start:
        return []
    if target not in previous_step:
        return []

    path: list[tuple[int, int]] = []
    cursor = target
    while cursor != start:
        path.append(cursor)
        cursor = previous_step.get(cursor)
        if cursor is None:
            return []
    path.reverse()
    return path


def draw_turn_controls(
    screen: pygame.Surface,
    panel_rect: pygame.Rect,
    start_y: int,
    mouse_pos: tuple[int, int],
    player: PlayerClass,
    turn_state: dict,
    dice_faces: dict[int, pygame.Surface],
    movement_dice_height: int,
    can_attack: bool,
    hide_controls: bool,
    title_font: pygame.font.Font,
    text_font: pygame.font.Font,
    zargon_active: bool = False,
) -> tuple[dict[str, pygame.Rect], pygame.Rect]:
    rects: dict[str, pygame.Rect] = {}

    if zargon_active:
        heading = title_font.render("Zargon's Turn", True, (210, 60, 60))
        screen.blit(heading, (panel_rect.x + 16, start_y + 4))
        status_surface = text_font.render("Enemies are acting…", True, TEXT_COLOR)
        screen.blit(status_surface, (panel_rect.x + 16, start_y + 40))
        controls_area = pygame.Rect(
            panel_rect.x + 8, start_y, panel_rect.width - 16, 60
        )
        return rects, controls_area

    heading = title_font.render(f"{player.name}'s Turn", True, ACCENT_COLOR)
    screen.blit(heading, (panel_rect.x + 16, start_y + 4))

    status_line = "Choose MOVE or ACTION"
    show_dice_roll = turn_state["mode"] == "move"
    if hide_controls:
        status_line = "Resolve combat"
    if turn_state["mode"] == "action":
        status_line = "Choose an action"
    elif turn_state["mode"] == "attack_target":
        status_line = "Select an adjacent enemy"
        hide_controls = True
    elif turn_state["selected_action"]:
        status_line = f"Action used: {turn_state['selected_action']}"

    flags = []
    if flags:
        status_line = f"{status_line} ({', '.join(flags)})"

    status_y = start_y + 40
    # movement_dice_height is drawn by the caller (under the menu). Use the
    # provided height to offset the control buttons so spacing remains correct.
    if not show_dice_roll:
        status_surface = text_font.render(status_line, True, TEXT_COLOR)
        screen.blit(status_surface, (panel_rect.x + 16, status_y))

    button_y = start_y + 92 + (movement_dice_height + 10 if movement_dice_height else 0)
    button_w = panel_rect.width - 32
    move_rect = pygame.Rect(panel_rect.x + 16, button_y, button_w, 42)
    action_rect = pygame.Rect(panel_rect.x + 16, button_y + 52, button_w, 42)
    controls_open = turn_state["mode"] == "action"

    rects["move"] = move_rect
    rects["action"] = action_rect

    # Draw MOVE and ACTION when controls are closed. When controls are
    # open we'll render the action list and then place PASS TURN at the end.
    if not controls_open and not hide_controls:
        move_enabled = not turn_state["moved"] and not turn_state["move_locked"]
        draw_button(screen, move_rect, "MOVE", mouse_pos, text_font, enabled=move_enabled)
        draw_button(screen, action_rect, "ACTION", mouse_pos, text_font, enabled=not turn_state["acted"])

    action_block_bottom = button_y
    if controls_open and not hide_controls:
        # Start the actions a bit below the main buttons area.
        action_y = button_y + 60
        for index, action_name in enumerate(ACTIONS):
            rect = pygame.Rect(panel_rect.x + 16, action_y + index * 42, button_w, 34)
            rects[f"action_{index}"] = rect
            # ACTIONS list contains uppercase names; compare case-insensitively
            enabled = can_attack if action_name.upper() == "ATTACK" else True
            draw_button(screen, rect, action_name, mouse_pos, text_font, enabled=enabled)

        # PASS TURN sits after the actions list when open
        pass_y = action_y + len(ACTIONS) * 42 + 12
        pass_rect = pygame.Rect(panel_rect.x + 16, pass_y, button_w, 42)
        rects["pass_turn"] = pass_rect
        draw_button(
            screen,
            pass_rect,
            "PASS TURN",
            mouse_pos,
            text_font,
            enabled=True,
            bg_color=PASS_BUTTON_BG,
            hover_bg_color=PASS_BUTTON_HOVER,
            border_color=PASS_BUTTON_BORDER,
        )
        action_block_bottom = pass_rect.bottom
    else:
        # PASS TURN position when controls are closed (unchanged behaviour)
        pass_y = button_y + 104
        pass_rect = pygame.Rect(panel_rect.x + 16, pass_y, button_w, 42)
        rects["pass_turn"] = pass_rect
        if not hide_controls:
            draw_button(
                screen,
                pass_rect,
                "PASS TURN",
                mouse_pos,
                text_font,
                enabled=True,
                bg_color=PASS_BUTTON_BG,
                hover_bg_color=PASS_BUTTON_HOVER,
                border_color=PASS_BUTTON_BORDER,
            )

    controls_area = pygame.Rect(
        panel_rect.x + 8,
        start_y,
        panel_rect.width - 16,
        action_block_bottom - start_y + 8,
    )
    return rects, controls_area

def draw_players_on_board(
    screen: pygame.Surface,
    board: Board,
    players: list[PlayerClass],
    token_icons: dict[str, pygame.Surface],
    active_player_name: str,
) -> None:
    for player in players:
        is_active = player.name == active_player_name
        col, row = player.cell
        cell_rect = board.cell_rect(col, row)
        token_size = max(18, min(cell_rect.width, cell_rect.height) - 10)
        raw_icon = token_icons.get(player.name)
        if raw_icon is None:
            # Fallback: create a simple colored square as icon if mapping is missing
            raw_icon = pygame.Surface((token_size, token_size))
            raw_icon.fill(player.color)
            token_icons[player.name] = raw_icon
        icon = circular_icon(raw_icon, token_size, dimmed=not is_active)

        # Handle player death fade-out if scheduled
        dying = getattr(player, "dying", False)
        if dying:
            now = pygame.time.get_ticks()
            start = int(getattr(player, "death_start", now))
            frac = min(1.0, max(0.0, (now - start) / DEATH_ANIM_MS))
            alpha = int(255 * (1.0 - frac))
            icon = icon.copy()
            icon.set_alpha(alpha)

        frame_rect = pygame.Rect(0, 0, token_size + 8, token_size + 8)
        frame_rect.center = cell_rect.center
        token_fill = player.color if is_active else tuple(max(35, channel // 2) for channel in player.color)
        pygame.draw.ellipse(screen, token_fill, frame_rect)
        border_color = ACCENT_COLOR if is_active else (120, 116, 110)
        border_width = 4 if is_active else 2
        pygame.draw.ellipse(screen, border_color, frame_rect, border_width)

        icon_rect = icon.get_rect(center=cell_rect.center)
        screen.blit(icon, icon_rect)


def load_enemy_icon(enemy: dict, size: int, font: pygame.font.Font) -> pygame.Surface:
    icon_file = str(enemy.get("icon_file", ""))
    path = ASSETS_DIR / "graphics" / "sprites" / icon_file
    if path.exists():
        raw = pygame.image.load(str(path)).convert()
        return pygame.transform.smoothscale(raw, (size, size))

    surface = pygame.Surface((size, size))
    color = tuple(enemy.get("color", [220, 40, 40]))
    surface.fill(color)
    label = font.render(str(enemy.get("display_name", enemy.get("name", "?")))[:1], True, (245, 240, 230))
    label_rect = label.get_rect(center=(size // 2, size // 2))
    surface.blit(label, label_rect)
    return surface


def draw_enemies_on_board(
    screen: pygame.Surface,
    board: Board,
    enemies: list[dict],
    enemy_icons: list[pygame.Surface],
    visible_enemies: set[int],
    reveal_all: bool,
    attackable_enemy_indexes: set[int] | None = None,
) -> None:
    attackable_enemy_indexes = attackable_enemy_indexes or set()
    now = pygame.time.get_ticks()
    for enemy_index, (enemy, icon_surface) in enumerate(zip(enemies, enemy_icons, strict=False)):
        if enemy.get("dying"):
            # allow showing dying enemy regardless of reveal_all so animation is visible
            pass
        elif not reveal_all and enemy_index not in visible_enemies:
            continue
        cell = enemy.get("cell")
        if not isinstance(cell, tuple) or len(cell) != 2:
            continue
        col, row = int(cell[0]), int(cell[1])
        if not dungeon_map.in_bounds(col, row):
            continue

        cell_rect = board.cell_rect(col, row)
        token_size = max(18, min(cell_rect.width, cell_rect.height) - 14)
        icon = circular_icon(icon_surface, token_size)

        frame_rect = pygame.Rect(0, 0, token_size + 8, token_size + 8)
        frame_rect.center = cell_rect.center

        # If the enemy is dying, compute fade-out alpha based on elapsed time.
        if enemy.get("dying"):
            start = int(enemy.get("death_start", now))
            elapsed = max(0, now - start)
            frac = min(1.0, elapsed / DEATH_ANIM_MS)
            alpha = int(255 * (1.0 - frac))
            color = tuple(enemy.get("color", [220, 40, 40])) + (alpha,)
            # draw fading ellipse on an SRCALPHA surface
            surf = pygame.Surface(frame_rect.size, pygame.SRCALPHA)
            pygame.draw.ellipse(surf, color, surf.get_rect())
            screen.blit(surf, frame_rect.topleft)
            # Draw icon with alpha
            icon = circular_icon(icon_surface, token_size)
            icon = icon.copy()
            icon.set_alpha(alpha)
            icon_rect = icon.get_rect(center=cell_rect.center)
            screen.blit(icon, icon_rect)
        else:
            color = tuple(enemy.get("color", [220, 40, 40]))
            pygame.draw.ellipse(screen, color, frame_rect)
            border_color = ACCENT_COLOR if enemy_index in attackable_enemy_indexes else (35, 20, 20)
            border_width = 3 if enemy_index in attackable_enemy_indexes else 2
            pygame.draw.ellipse(screen, border_color, frame_rect, border_width)

            icon_rect = icon.get_rect(center=cell_rect.center)
            screen.blit(icon, icon_rect)


def build_enemy_menu_rows(
    enemies: list[dict],
    enemy_icons: list[pygame.Surface],
    visible_enemies: set[int],
    reveal_all: bool,
) -> list[dict]:
    grouped: dict[str, dict] = {}
    for enemy_index, enemy in enumerate(enemies):
        # Skip enemies that are in death animation
        if enemy.get("dying"):
            continue
        if not reveal_all and enemy_index not in visible_enemies:
            continue

        type_name = str(enemy.get("name", "Enemy"))
        group = grouped.get(type_name)
        if group is None:
            group = {
                "name": type_name,
                "hp": int(enemy.get("hp", enemy.get("max_hp", 1))),
                "max_hp": int(enemy.get("max_hp", enemy.get("hp", 1))),
                "move": int(enemy.get("move", 0)),
                "attack_dice": int(enemy.get("attack_dice", 0)),
                "defense_dice": int(enemy.get("defense_dice", 0)),
                "mind": int(enemy.get("mind", 0)),
                "visible_count": 1,
                "icon": enemy_icons[enemy_index],
            }
            grouped[type_name] = group
        else:
            group["visible_count"] += 1

    return list(grouped.values())


def _normalize_enemy_name(name: str) -> str:
    normalized = name.strip().lower()
    aliases = {
        "mummie": "mummy",
    }
    return aliases.get(normalized, normalized)


def extract_quest_enemies(quest_payload: dict, enemy_catalog: list[dict]) -> list[dict]:
    catalog_by_name = {
        _normalize_enemy_name(str(enemy.get("name", ""))): enemy
        for enemy in enemy_catalog
    }

    quest_entries = quest_payload.get("ennemies")
    if not isinstance(quest_entries, list):
        quest_entries = quest_payload.get("enemies", [])
    if not isinstance(quest_entries, list):
        return []

    instances: list[dict] = []
    for item in quest_entries:
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name", "")).strip()
        key = _normalize_enemy_name(raw_name)
        template = catalog_by_name.get(key)
        if template is None:
            continue

        position = item.get("position")
        if not isinstance(position, list) or len(position) != 2:
            continue

        col = int(position[0])
        row = int(position[1])
        if not dungeon_map.in_bounds(col, row):
            continue

        display_name = str(item.get("special", "")).strip() or str(template.get("name", raw_name))
        hp = int(template.get("hp", 1))
        enemy_instance = {
            "name": str(template.get("name", raw_name)),
            "display_name": display_name,
            "hp": hp,
            "max_hp": int(template.get("max_hp", hp)),
            "attack_dice": int(template.get("attack_dice", 0)),
            "defense_dice": int(template.get("defense_dice", 0)),
            "mind": int(template.get("mind", 0)),
            "move": int(template.get("move", 0)),
            "icon_file": str(template.get("icon_file", "")),
            "dying_sound": str(template.get("dying_sound", "")),
            "color": tuple(template.get("color", [220, 40, 40])),
            "cell": (col, row),
            "rotation": int(item.get("rotation", 0)) % 4,
        }
        instances.append(enemy_instance)

    return instances


def new_panel_transition() -> dict:
    return {
        "active": False,
        "elapsed": 0,
        "duration": PANEL_TRANSITION_MS,
        "rect": None,
    }

def start_panel_transition(transition: dict, rect: pygame.Rect | None) -> None:
    transition["active"] = True
    transition["elapsed"] = 0
    transition["rect"] = rect.copy() if rect else None


def update_panel_transition(transition: dict, dt: int) -> None:
    if not transition["active"]:
        return
    transition["elapsed"] += dt
    if transition["elapsed"] >= transition["duration"]:
        transition["active"] = False
        transition["elapsed"] = transition["duration"]


def draw_panel_transition(screen: pygame.Surface, panel_rect: pygame.Rect, transition: dict) -> None:
    if not transition["active"]:
        return
    target_rect = transition.get("rect")
    if not target_rect:
        return
    progress = transition["elapsed"] / max(1, transition["duration"])

def new_zargon_state() -> dict:
    """Return fresh state for the enemy (Zargon) AI turn."""
    return {
        # List of enemy indices that still need to act this turn (shuffled).
        "enemy_queue": [],
        # Index into enemies[] that is currently acting, or None.
        "current_enemy_idx": None,
        # Remaining movement steps for the current enemy.
        "steps_left": 0,
        # Timestamp of the last step movement (ms), used for pacing.
        "step_timer": 0,
        # ms between each movement step animation.
        "step_interval_ms": 220,
        # Sub-phase for the current enemy: "move" or "attack" or "done".
        "phase": "idle",
        # Enemy-attacks-hero dialog (same shape as hero attack_dialog but
        # "attacker" is an enemy dict and "defender_index" indexes players).
        "attack_dialog": None,
        # Timestamp when the auto-advance dialog phase started.
        "dialog_phase_start": 0,
        # ms per dialog phase (0 → 1 → 2) during auto-advance.
        "dialog_phase_ms": 900,
    }


def enemy_next_step_toward_heroes(
    enemy_cell: tuple[int, int],
    heroes: list[PlayerClass],
    all_enemies: list[dict],
    door_states: dict,
) -> tuple[int, int] | None:
    """BFS from enemy_cell toward the nearest live hero.

    Returns the first step cell (adjacent to enemy_cell) that is on the
    shortest path toward any hero, or None if already adjacent / no path.
    """
    live_hero_cells = {
        p.cell
        for p in heroes
        if isinstance(p.cell, tuple) and len(p.cell) == 2 and not getattr(p, "dying", False)
    }
    if not live_hero_cells:
        return None

    # Already adjacent to a hero with no wall between them? → no movement needed.
    ec_col, ec_row = enemy_cell
    for hero_cell in live_hero_cells:
        if cells_are_attack_adjacent(enemy_cell, hero_cell, door_states):
            return None

    # BFS outward from enemy_cell; stop when a hero cell is reached.
    # Enemies cannot move through other enemies or heroes (hero cells are
    # treated as hard stop but reachable for targeting purposes).
    enemy_occupied = {
        e.get("cell")
        for e in all_enemies
        if isinstance(e.get("cell"), tuple) and e.get("cell") != enemy_cell and not e.get("dying")
    }
    hero_occupied = set(live_hero_cells)

    visited: set[tuple[int, int]] = {enemy_cell}
    # Each queue item: (cell, first_step) — first_step is the immediate
    # neighbour we took from enemy_cell to reach this cell.
    frontier: list[tuple[tuple[int, int], tuple[int, int]]] = []

    for direction, (dc, dr) in DIR_OFFSETS.items():
        nc, nr = ec_col + dc, ec_row + dr
        if not dungeon_map.in_bounds(nc, nr):
            continue
        if not is_passable_with_doors(ec_col, ec_row, direction, door_states):
            continue
        target_kind = dungeon_map.cell_kind(nc, nr)
        if target_kind in {CellKind.VOID, CellKind.BLOCKED}:
            continue
        ncell = (nc, nr)
        if ncell in enemy_occupied:
            continue
        visited.add(ncell)
        frontier.append((ncell, ncell))

    while frontier:
        cur_cell, first_step = frontier.pop(0)
        if cur_cell in hero_occupied:
            return first_step

        cc, cr = cur_cell
        for direction, (dc, dr) in DIR_OFFSETS.items():
            nc, nr = cc + dc, cr + dr
            if not dungeon_map.in_bounds(nc, nr):
                continue
            ncell = (nc, nr)
            if ncell in visited:
                continue
            if not is_passable_with_doors(cc, cr, direction, door_states):
                continue
            target_kind = dungeon_map.cell_kind(nc, nr)
            if target_kind in {CellKind.VOID, CellKind.BLOCKED}:
                continue
            if ncell in enemy_occupied:
                continue
            visited.add(ncell)
            frontier.append((ncell, first_step))

    return None


def new_turn_state() -> dict:
    return {
        "moved": False,
        "acted": False,
        "move_locked": False,
        "mode": None,
        "move_points": 0,
        "move_points_initial": 0,
        "move_origin_cell": None,
        "dice_roll": (0, 0),
        "reachable_cells": set(),
        "reachable_costs": {},
        "reachable_prev": {},
        "selected_action": None,
        "attack_candidates": [],
        "attack_dialog": None,
    }


def run_splash(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    duration_ms: int,
    fade_ms: int,
) -> None:
    """Display the box-art splash screen.

    The player can skip it early with any key or mouse click.
    """
    ww, wh = screen.get_size()
    raw = pygame.image.load(str(SPLASH_IMAGE)).convert()
    splash = pygame.transform.smoothscale(raw, (ww, wh))

    font = pygame.font.SysFont("freesansbold", 22)
    hint = font.render("Press any key to continue", True, ACCENT_COLOR)
    hint_rect = hint.get_rect(center=(ww // 2, wh - 30))

    elapsed = 0
    skipped = False
    while elapsed < duration_ms and not skipped:
        dt = clock.tick(60)
        elapsed += dt
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit(0)
            if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                skipped = True

        screen.blit(splash, (0, 0))
        screen.blit(hint, hint_rect)
        pygame.display.flip()

    # Fade to black
    fade = pygame.Surface((ww, wh))
    fade.fill((0, 0, 0))
    fade_elapsed = 0
    while fade_elapsed < fade_ms:
        dt = clock.tick(60)
        fade_elapsed += dt
        # Drain events so they don't pile up and fire spuriously in the game loop.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit(0)
        alpha = min(255, int(255 * fade_elapsed / fade_ms)) if fade_ms else 255
        fade.set_alpha(alpha)
        screen.blit(splash, (0, 0))
        screen.blit(hint, hint_rect)
        screen.blit(fade, (0, 0))
        pygame.display.flip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    cfg = _load_config(args.debug)

    pygame.init()

    audio_mod.init_audio(cfg)

    if audio_mod.audio_enabled and audio_mod.music_enabled and audio_mod.music_tracks:
        pygame.mixer.music.set_endevent(MUSIC_END_EVENT)
        audio_mod.play_random_music_track()

    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("Hero Quest")
    clock = pygame.time.Clock()

    if SPLASH_IMAGE.exists():
        run_splash(screen, clock, cfg["SPLASH_DURATION_MS"], cfg["SPLASH_FADE_MS"])

    # Apply final gameplay display mode after splash.
    if cfg["FULLSCREEN"]:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.event.clear()

    players = load_players()
    enemy_catalog = load_enemies()
    enemies = enemy_catalog
    title_font = pygame.font.SysFont("freesansbold", 30)
    text_font = pygame.font.SysFont("freesansbold", 22)
    fallback_font = pygame.font.SysFont("freesansbold", 20)
    dice_faces = load_die_faces(40, fallback_font)
    combat_face_sprites = load_combat_face_sprites(44, fallback_font)
    object_definitions = load_object_definitions()
    solid_rock_cells: set[tuple[int, int]] = set()
    door_states: dict[DoorKey, bool] = {}
    secret_door_keys: set[DoorKey] = set()
    # Maps a newly-revealed secret door key to the ticks timestamp when it was
    # revealed, so draw_doors_on_board can fade it in over 1 second.
    secret_door_reveal_times: dict[DoorKey, int] = {}
    door_open_path, door_closed_path, door_secret_path = load_door_image_paths()
    dungeon_rooms = load_dungeon_rooms()
    reveal_all = False
    los_debug_overlay = False
    visible_objects: set[ObjectInstanceKey] = set()
    visible_doors: set[DoorKey] = set()
    visible_enemies: set[int] = set()

    # temporary: load quest #1
    if True:
        quest_payload = load_quest_payload(DEBUG_DEFAULT_QUEST)
        if quest_payload:
            validate_quest_objects(object_definitions, quest_payload, DEBUG_DEFAULT_QUEST)
            validate_solid_rock_areas(quest_payload, DEBUG_DEFAULT_QUEST)
            validate_doors(quest_payload, DEBUG_DEFAULT_QUEST)
            apply_quest_object_placements(object_definitions, quest_payload)
            solid_rock_cells = extract_solid_rock_cells(quest_payload)
            door_states, secret_door_keys = extract_door_states(quest_payload)
            enemies = extract_quest_enemies(quest_payload, enemy_catalog)
            assign_players_to_stairs_start(players, object_definitions)
            apply_furniture_blocking_to_world(object_definitions)
            apply_solid_rock_blocking_to_world(solid_rock_cells)

    def build_layout() -> tuple[
        pygame.Rect,
        Board,
        dict[str, pygame.Surface],
        dict[str, pygame.Surface],
        list[pygame.Surface],
        dict[tuple[str, tuple[int, int], int], pygame.Surface],
        dict[tuple[bool | str, str], pygame.Surface],
    ]:
        screen_w, screen_h = screen.get_size()
        panel_w = min(360, max(280, screen_w // 4))
        menu_rect = pygame.Rect(0, 0, panel_w, screen_h)
        game_board = Board(screen, left_offset=panel_w)
        menu_icons = {
            player.name: load_player_icon(player, 44, fallback_font)
            for player in players
        }
        board_icon_size = max(24, game_board.cell_size - 10)
        board_icons = {
            player.name: load_player_icon(player, board_icon_size, fallback_font)
            for player in players
        }
        enemy_icon_size = max(20, board_icon_size - 4)
        enemy_icons = [
            load_enemy_icon(enemy, enemy_icon_size, fallback_font)
            for enemy in enemies
        ]
        object_sprites: dict[tuple[str, tuple[int, int], int], pygame.Surface] = {}
        for definition in object_definitions:
            variants = {(definition.size, 0)}
            variants.update((placement.size, placement.rotation) for placement in definition.placements)
            for size, rotation in variants:
                object_sprites[(definition.object_id, size, rotation)] = load_object_sprite(
                    definition,
                    game_board.cell_size,
                    fallback_font,
                    size=size,
                    rotation=rotation,
                    fill_ratio=0.9,
                )
        door_sprites = load_door_sprites(door_open_path, door_closed_path, game_board, door_secret_path)
        return menu_rect, game_board, menu_icons, board_icons, enemy_icons, object_sprites, door_sprites

    panel_rect, board, menu_icons, board_icons, enemy_icons, object_sprites, door_sprites = build_layout()
    active_player_index = 0
    turn_state = new_turn_state()
    panel_transition = new_panel_transition()
    control_rects: dict[str, pygame.Rect] = {}
    controls_area_rect = pygame.Rect(0, 0, 0, 0)
    # Zargon (enemy AI) turn state; None means it's not Zargon's turn.
    zargon_state: dict | None = None

    # Debris is decorative and should be visible from the start.
    for definition in object_definitions:
        if definition.object_id != "debris":
            continue
        for placement_index, _ in enumerate(definition.placements):
            visible_objects.add((definition.object_id, placement_index))

    for player in players:
        update_visibility_from_player(
            player,
            players,
            door_states,
            object_definitions,
            enemies,
            visible_objects,
            visible_doors,
            visible_enemies,
            secret_door_keys,
        )

    # Pre-populate control_rects AFTER the initial visibility pass so that
    # enemy_menu_rows reflects the real starting state (same as frame 1).
    _dummy = pygame.Surface(screen.get_size())
    _dummy_enemy_rows = build_enemy_menu_rows(enemies, enemy_icons, visible_enemies, reveal_all)
    _, _controls_y = draw_left_menu(
        _dummy,
        panel_rect,
        (-1, -1),
        players,
        menu_icons,
        players[active_player_index].name,
        _dummy_enemy_rows,
        title_font,
        text_font,
    )
    control_rects, controls_area_rect = draw_turn_controls(
        _dummy,
        panel_rect,
        _controls_y + 12,
        (-1, -1),
        players[active_player_index],
        turn_state,
        dice_faces,
        0,
        False,
        False,
        title_font,
        text_font,
    )
    del _dummy

    def open_attack_dialog(attacker: PlayerClass, target_index: int) -> None:
        if not (0 <= target_index < len(enemies)):
            return
        outcome = compute_attack_outcome(attacker, enemies[target_index])
        turn_state["mode"] = "attack_dialog"
        turn_state["attack_candidates"] = [target_index]
        turn_state["reachable_cells"] = set()
        turn_state["reachable_costs"] = {}
        turn_state["reachable_prev"] = {}
        turn_state["attack_dialog"] = {
            "target_index": target_index,
            "outcome": outcome,
            "phase": 0,          # player must click to roll attacker dice
            "attacker_rotations": roll_dice_rotations(len(outcome["attack_rolls"])),
            "defender_rotations": roll_dice_rotations(len(outcome["defense_rolls"])),
            # phase1_rolled_at: set when attacker dice are shown, triggers
            # the 1-second automatic defender roll.
            "phase1_rolled_at": None,
        }
        start_panel_transition(panel_transition, controls_area_rect)

    running = True
    while running:
        active_player = players[active_player_index]
        frame_dt = clock.tick(60)
        update_panel_transition(panel_transition, frame_dt)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == MUSIC_END_EVENT:
                audio_mod.play_random_music_track()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            if event.type == pygame.KEYDOWN and args.debug and event.key == pygame.K_v:
                reveal_all = not reveal_all
            if event.type == pygame.KEYDOWN and args.debug and event.key == pygame.K_l:
                los_debug_overlay = not los_debug_overlay
            if event.type in (pygame.WINDOWSIZECHANGED, pygame.VIDEORESIZE):
                panel_rect, board, menu_icons, board_icons, enemy_icons, object_sprites, door_sprites = build_layout()
            if event.type == pygame.MOUSEBUTTONDOWN:
                mouse_pos = event.pos

                # During Zargon's turn, only allow clicks when the enemy-attack
                # dialog is waiting for the player (phase 1 = roll defence dice,
                # phase 2 = close / resolve).
                if zargon_state is not None:
                    zdialog = zargon_state.get("attack_dialog")
                    if event.button == 1 and zdialog is not None:
                        zphase = int(zdialog.get("phase", 0))
                        now_click = pygame.time.get_ticks()
                        if zphase == 1:
                            # Player rolls the hero's defence dice
                            audio_mod.play_sfx("dice_roll")
                            outcome = zdialog["outcome"]
                            zdialog["defender_rotations"] = roll_dice_rotations(len(outcome["defense_rolls"]))
                            sfx_list = ["shield.mp3" for _ in range(int(outcome["saves"]))]
                            sfx_list += ["damage.mp3" for _ in range(int(outcome["damage"]))]
                            zdialog["sfx_queue"] = sfx_list
                            zdialog["sfx_next_time"] = now_click + 600
                            zdialog["phase"] = 2
                            zargon_state["dialog_phase_start"] = now_click
                            # Apply damage immediately so the left menu shows
                            # the updated HP while the result dialog is still open.
                            defender_idx = int(zdialog.get("defender_index", 0))
                            if 0 <= defender_idx < len(players):
                                hero = players[defender_idx]
                                hero.hp = int(outcome["defender_hp_after"])
                                if outcome["defender_dead"]:
                                    dying_sound = hero.dying_sound
                                    if dying_sound:
                                        audio_mod.play_named_sound(dying_sound)
                                    hero.dying = True
                                    hero.death_start = now_click
                        elif zphase == 2:
                            # HP already applied at phase 1→2 transition; just close.
                            zargon_state["attack_dialog"] = None
                            zargon_state["phase"] = "next"
                    continue

                if event.button == 3 and turn_state["mode"] == "move":
                    origin = turn_state["move_origin_cell"]
                    if origin is not None:
                        active_player.cell = origin
                    turn_state["moved"] = False
                    turn_state["move_points"] = turn_state["move_points_initial"]
                    turn_state["reachable_costs"], turn_state["reachable_prev"] = compute_reachable_cells(
                        active_player,
                        players,
                        enemies,
                        turn_state["move_points"],
                        GRID_COLS,
                        GRID_ROWS,
                        door_states,
                    )
                    turn_state["reachable_cells"] = set(turn_state["reachable_costs"].keys())

                if event.button == 1:
                    if turn_state["attack_dialog"] is not None:
                        dialog = turn_state["attack_dialog"]
                        outcome = dialog["outcome"]
                        phase = int(dialog.get("phase", 0))
                        now_click = pygame.time.get_ticks()
                        if phase == 0:
                            # First click: roll attacker dice; defender rolls
                            # automatically after 1 second.
                            audio_mod.play_sfx("dice_roll")
                            sfx_list: list[str] = ["sword.mp3" for _ in range(int(outcome["skulls"]))]
                            dialog["sfx_queue"] = sfx_list
                            dialog["sfx_next_time"] = now_click + 800
                            dialog["phase"] = 1
                            dialog["phase1_rolled_at"] = now_click
                        elif phase == 2:
                            # Second click: resolve combat and close dialog.
                            target_index = int(dialog["target_index"])
                            if 0 <= target_index < len(enemies):
                                enemies[target_index]["hp"] = int(outcome["defender_hp_after"])
                                if outcome["defender_dead"]:
                                    dying_sound = str(enemies[target_index].get("dying_sound", ""))
                                    if dying_sound:
                                        audio_mod.play_named_sound(dying_sound)
                                    enemies[target_index]["dying"] = True
                                    enemies[target_index]["death_start"] = now_click
                                    visible_enemies = {i for i in visible_enemies if i != target_index}
                            turn_state["acted"] = True
                            turn_state["selected_action"] = "Attack"
                            turn_state["mode"] = None
                            turn_state["attack_candidates"] = []
                            turn_state["attack_dialog"] = None
                        start_panel_transition(panel_transition, controls_area_rect)
                        continue

                    if turn_state["mode"] == "attack_target":
                        clicked_cell = board.px_to_cell(*mouse_pos)
                        if clicked_cell is not None:
                            target_index = next(
                                (
                                    idx
                                    for idx in turn_state["attack_candidates"]
                                    if isinstance(enemies[idx].get("cell"), tuple) and enemies[idx].get("cell") == clicked_cell
                                ),
                                None,
                            )
                            if target_index is not None:
                                open_attack_dialog(active_player, target_index)
                                continue

                    clicked_cell = board.px_to_cell(*mouse_pos)
                    if (
                        not turn_state["acted"]
                        and turn_state["attack_dialog"] is None
                        and clicked_cell is not None
                    ):
                        adjacent_targets = adjacent_enemy_indexes(active_player.cell, enemies, door_states)
                        target_index = next(
                            (
                                idx
                                for idx in adjacent_targets
                                if isinstance(enemies[idx].get("cell"), tuple) and enemies[idx].get("cell") == clicked_cell
                            ),
                            None,
                        )
                        if target_index is not None:
                            open_attack_dialog(active_player, target_index)
                            continue

                    opened_door = try_open_clicked_door(
                        mouse_pos,
                        board,
                        active_player,
                        door_states,
                        visible_doors,
                        reveal_all,
                    )
                    if opened_door:
                        audio_mod.play_sfx("door_open")
                        # A secret door becomes a normal door once opened.
                        secret_door_keys.discard(opened_door)
                        reveal_room_from_opened_door(
                            opened_door,
                            door_states,
                            object_definitions,
                            enemies,
                            visible_objects,
                            visible_doors,
                            visible_enemies,
                        )
                        update_visibility_from_player(
                            active_player,
                            players,
                            door_states,
                            object_definitions,
                            enemies,
                            visible_objects,
                            visible_doors,
                            visible_enemies,
                            secret_door_keys,
                        )
                        if turn_state["mode"] == "move":
                            turn_state["reachable_costs"], turn_state["reachable_prev"] = compute_reachable_cells(
                                active_player,
                                players,
                                enemies,
                                turn_state["move_points"],
                                GRID_COLS,
                                GRID_ROWS,
                                door_states,
                            )
                            turn_state["reachable_cells"] = set(turn_state["reachable_costs"].keys())
                        continue

                    if turn_state["mode"] == "move":
                        clicked_cell = board.px_to_cell(*mouse_pos)
                        move_cost = turn_state["reachable_costs"].get(clicked_cell) if clicked_cell else None
                        if move_cost is not None:
                            path_cells = reconstruct_path(turn_state["reachable_prev"], active_player.cell, clicked_cell)
                            if not path_cells:
                                path_cells = [clicked_cell]
                            for step_cell in path_cells:
                                active_player.cell = step_cell
                                update_visibility_from_player(
                                    active_player,
                                    players,
                                    door_states,
                                    object_definitions,
                                    enemies,
                                    visible_objects,
                                    visible_doors,
                                    visible_enemies,
                                    secret_door_keys,
                                )
                            audio_mod.play_sfx("move")
                            turn_state["move_points"] = max(0, turn_state["move_points"] - move_cost)
                            turn_state["moved"] = True
                            if turn_state["move_points"] > 0:
                                turn_state["reachable_costs"], turn_state["reachable_prev"] = compute_reachable_cells(
                                    active_player,
                                    players,
                                    enemies,
                                    turn_state["move_points"],
                                    GRID_COLS,
                                    GRID_ROWS,
                                    door_states,
                                )
                                turn_state["reachable_cells"] = set(turn_state["reachable_costs"].keys())
                            else:
                                turn_state["reachable_cells"] = set()
                                turn_state["reachable_costs"] = {}
                                turn_state["reachable_prev"] = {}

                    if (
                        control_rects.get("move")
                        and control_rects["move"].collidepoint(mouse_pos)
                        and not turn_state["moved"]
                        and not turn_state["move_locked"]
                    ):
                        die_one = random.randint(1, 6)
                        die_two = random.randint(1, 6)
                        audio_mod.play_sfx("dice_roll")
                        # store random rotations for the two movement dice
                        turn_state["dice_rotations"] = roll_dice_rotations(2)
                        move_points = die_one + die_two
                        turn_state["dice_roll"] = (die_one, die_two)
                        turn_state["move_points"] = move_points
                        turn_state["move_points_initial"] = move_points
                        turn_state["move_origin_cell"] = active_player.cell
                        turn_state["move_locked"] = True
                        turn_state["reachable_costs"], turn_state["reachable_prev"] = compute_reachable_cells(
                            active_player,
                            players,
                            enemies,
                            move_points,
                            GRID_COLS,
                            GRID_ROWS,
                            door_states,
                        )
                        turn_state["reachable_cells"] = set(turn_state["reachable_costs"].keys())
                        turn_state["mode"] = "move"
                        if not turn_state["reachable_cells"]:
                            turn_state["mode"] = None
                        start_panel_transition(panel_transition, controls_area_rect)

                    # Only open the action menu when it's not already open. This
                    # prevents clicks on the action-list items from also toggling
                    # the main ACTION button (which produced a stray click sound).
                    if (
                        control_rects.get("action")
                        and control_rects["action"].collidepoint(mouse_pos)
                        and not turn_state["acted"]
                        and turn_state["mode"] != "action"
                    ):
                        audio_mod.play_sfx("click")
                        turn_state["mode"] = "action"
                        turn_state["reachable_cells"] = set()
                        turn_state["reachable_costs"] = {}
                        turn_state["move_points"] = 0
                        start_panel_transition(panel_transition, controls_area_rect)

                    if control_rects.get("pass_turn") and control_rects["pass_turn"].collidepoint(mouse_pos):
                        audio_mod.play_sfx("click")
                        next_index = (active_player_index + 1) % len(players)
                        if next_index == 0 and zargon_state is None:
                            # All heroes have passed — start Zargon's turn.
                            zargon_state = new_zargon_state()
                        active_player_index = next_index
                        turn_state = new_turn_state()
                        active_player = players[active_player_index]
                        start_panel_transition(panel_transition, controls_area_rect)

                    if turn_state["mode"] == "action":
                        handled_click = False
                        for index, action_name in enumerate(ACTIONS):
                            rect = control_rects.get(f"action_{index}")
                            if rect and rect.collidepoint(mouse_pos):
                                # Determine whether this action is enabled. Attack is
                                # only enabled when there are adjacent enemies.
                                enabled = True
                                if action_name.upper() == "ATTACK":
                                    attack_candidates = adjacent_enemy_indexes(active_player.cell, enemies, door_states)
                                    enabled = bool(attack_candidates)
                                if not enabled:
                                    # Consume the click but do nothing (no sound)
                                    handled_click = True
                                    break

                                handled_click = True
                                if action_name.upper() == "ATTACK":
                                    audio_mod.play_sfx("click")
                                    turn_state["mode"] = "attack_target"
                                    turn_state["attack_candidates"] = attack_candidates
                                    start_panel_transition(panel_transition, controls_area_rect)
                                    break

                                if action_name.upper() == "SEARCH FOR SECRET DOORS":
                                    newly_found = search_for_secret_doors(
                                        active_player,
                                        door_states,
                                        secret_door_keys,
                                        dungeon_rooms,
                                        visible_doors,
                                    )
                                    if newly_found:
                                        now_reveal = pygame.time.get_ticks()
                                        for dk in newly_found:
                                            secret_door_reveal_times[dk] = now_reveal
                                        audio_mod.play_named_sound("secret_found.mp3")
                                    else:
                                        audio_mod.play_named_sound("fail.mp3")
                                    turn_state["acted"] = True
                                    turn_state["selected_action"] = action_name
                                    turn_state["mode"] = None
                                    start_panel_transition(panel_transition, controls_area_rect)
                                    break

                                audio_mod.play_sfx("click")
                                turn_state["acted"] = True
                                turn_state["selected_action"] = action_name
                                turn_state["mode"] = None
                                start_panel_transition(panel_transition, controls_area_rect)
                                break
                        if handled_click:
                            # Skip other click processing when an action button was clicked
                            continue

                    if turn_state["moved"] and turn_state["acted"]:
                        next_index = (active_player_index + 1) % len(players)
                        if next_index == 0 and zargon_state is None:
                            # All heroes have acted — start Zargon's turn.
                            zargon_state = new_zargon_state()
                        active_player_index = next_index
                        turn_state = new_turn_state()
                        active_player = players[active_player_index]
                        start_panel_transition(panel_transition, controls_area_rect)

        # Process queued combat SFX and automatic phase advance for hero attack dialog.
        if turn_state.get("attack_dialog") is not None:
            dialog = turn_state["attack_dialog"]
            now = pygame.time.get_ticks()

            # After the attacker dice are shown (phase 1), automatically roll
            # the defender dice 1 second later.
            if int(dialog.get("phase", 0)) == 1:
                rolled_at = dialog.get("phase1_rolled_at")
                if rolled_at is not None and now - rolled_at >= 1000:
                    outcome = dialog["outcome"]
                    audio_mod.play_sfx("dice_roll")
                    sfx_list = ["shield.mp3" for _ in range(int(outcome["saves"]))]
                    sfx_list += ["damage.mp3" for _ in range(int(outcome["damage"]))]
                    existing = dialog.get("sfx_queue") or []
                    dialog["sfx_queue"] = existing + sfx_list
                    if dialog.get("sfx_next_time") is None:
                        dialog["sfx_next_time"] = now + 600
                    dialog["phase"] = 2
                    dialog["phase1_rolled_at"] = None

            sfx_queue = dialog.get("sfx_queue")
            next_time = dialog.get("sfx_next_time")
            if sfx_queue and next_time is not None:
                if now >= next_time and len(sfx_queue) > 0:
                    sound_file = sfx_queue.pop(0)
                    audio_mod.play_named_sound(sound_file)
                    dialog["sfx_next_time"] = now + 700 if sfx_queue else None
                if not sfx_queue:
                    dialog.pop("sfx_queue", None)
                    dialog.pop("sfx_next_time", None)

        # ── Zargon (enemy AI) turn update ────────────────────────────────
        if zargon_state is not None:
            zs = zargon_state
            now = pygame.time.get_ticks()

            # ── Phase: auto-advance enemy→hero attack dialog ──────────────
            if zs["attack_dialog"] is not None:
                zdialog = zs["attack_dialog"]
                zphase = int(zdialog.get("phase", 0))
                elapsed_in_phase = now - zs["dialog_phase_start"]

                # Only phase 0 (enemy attack roll) is automatic; phases 1+
                # are driven by the player clicking.
                if zphase == 0 and elapsed_in_phase >= zs["dialog_phase_ms"]:
                    # Auto-roll attacker dice (enemy skulls)
                    audio_mod.play_sfx("dice_roll")
                    outcome = zdialog["outcome"]
                    zdialog["attacker_rotations"] = roll_dice_rotations(len(outcome["attack_rolls"]))
                    sfx_list = ["sword.mp3" for _ in range(int(outcome["skulls"]))]
                    zdialog["sfx_queue"] = sfx_list
                    zdialog["sfx_next_time"] = now + 600
                    zdialog["phase"] = 1
                    zs["dialog_phase_start"] = now

                # Process queued SFX for zargon dialog
                sfx_queue = zdialog.get("sfx_queue")
                sfx_next = zdialog.get("sfx_next_time")
                if sfx_queue and sfx_next is not None and now >= sfx_next:
                    audio_mod.play_named_sound(sfx_queue.pop(0))
                    zdialog["sfx_next_time"] = now + 700 if sfx_queue else None
                    if not sfx_queue:
                        zdialog.pop("sfx_queue", None)
                        zdialog.pop("sfx_next_time", None)

            # ── Phase: initialize or advance to next enemy ─────────────────
            elif zs["phase"] in ("idle", "next"):
                if zs["phase"] == "idle":
                    # Build queue of visible enemies (in random order)
                    candidates = [i for i in visible_enemies if not enemies[i].get("dying")]
                    random.shuffle(candidates)
                    zs["enemy_queue"] = candidates
                # Pop next enemy from queue
                while zs["enemy_queue"]:
                    idx = zs["enemy_queue"].pop(0)
                    if idx < len(enemies) and not enemies[idx].get("dying"):
                        zs["current_enemy_idx"] = idx
                        move_max = int(enemies[idx].get("move", 0))
                        zs["steps_left"] = move_max
                        zs["step_timer"] = now
                        zs["phase"] = "move"
                        break
                else:
                    # Queue empty — Zargon's turn is over
                    zargon_state = None

            # ── Phase: move current enemy one step at a time ───────────────
            elif zs["phase"] == "move":
                idx = zs["current_enemy_idx"]
                if idx is None or idx >= len(enemies) or enemies[idx].get("dying"):
                    zs["phase"] = "next"
                elif zs["steps_left"] <= 0:
                    zs["phase"] = "attack"
                elif now - zs["step_timer"] >= zs["step_interval_ms"]:
                    enemy = enemies[idx]
                    next_cell = enemy_next_step_toward_heroes(
                        enemy["cell"], players, enemies, door_states
                    )
                    if next_cell is not None:
                        old_cell = enemy["cell"]
                        enemy["cell"] = next_cell
                        # Reveal the enemy's new cell to players
                        for player in players:
                            update_visibility_from_player(
                                player, players, door_states, object_definitions,
                                enemies, visible_objects, visible_doors, visible_enemies,
                                secret_door_keys,
                            )
                        audio_mod.play_sfx("move")
                        zs["steps_left"] -= 1
                        zs["step_timer"] = now
                        # Check adjacency (no wall): if now adjacent to a hero, stop and attack
                        live_heroes = [p for p in players if not getattr(p, "dying", False)]
                        adjacent_hero = next(
                            (
                                p for p in live_heroes
                                if isinstance(p.cell, tuple) and
                                cells_are_attack_adjacent(enemy["cell"], p.cell, door_states)
                            ),
                            None,
                        )
                        if adjacent_hero is not None:
                            zs["steps_left"] = 0
                            zs["phase"] = "attack"
                    else:
                        # No valid step (already adjacent or blocked)
                        zs["steps_left"] = 0
                        zs["phase"] = "attack"

            # ── Phase: enemy attacks adjacent hero ─────────────────────────
            elif zs["phase"] == "attack":
                idx = zs["current_enemy_idx"]
                if idx is None or idx >= len(enemies) or enemies[idx].get("dying"):
                    zs["phase"] = "next"
                else:
                    enemy = enemies[idx]
                    live_heroes = [
                        (hi, p)
                        for hi, p in enumerate(players)
                        if not getattr(p, "dying", False)
                        and isinstance(p.cell, tuple)
                        and cells_are_attack_adjacent(enemy["cell"], p.cell, door_states)
                    ]
                    if live_heroes:
                        # Pick random adjacent hero to attack
                        hero_idx, hero = random.choice(live_heroes)
                        outcome = compute_attack_outcome_enemy(enemy, hero)
                        attacker_icon = enemy_icons[idx] if idx < len(enemy_icons) else None
                        defender_icon = menu_icons.get(hero.name)
                        if attacker_icon is None:
                            attacker_icon = pygame.Surface((44, 44))
                            attacker_icon.fill((220, 40, 40))
                        if defender_icon is None:
                            defender_icon = pygame.Surface((44, 44))
                            defender_icon.fill((100, 100, 200))
                        zs["attack_dialog"] = {
                            "enemy_index": idx,
                            "defender_index": hero_idx,
                            "outcome": outcome,
                            "phase": 0,
                            "attacker_rotations": roll_dice_rotations(len(outcome["attack_rolls"])),
                            "defender_rotations": roll_dice_rotations(len(outcome["defense_rolls"])),
                            "attacker_icon": attacker_icon,
                            "defender_icon": defender_icon,
                            "attacker_name": str(enemy.get("display_name", enemy.get("name", "Enemy"))),
                            "defender_name": hero.name,
                        }
                        zs["dialog_phase_start"] = now
                        zs["phase"] = "dialog"
                    else:
                        zs["phase"] = "next"

        screen.fill(BACKGROUND_COLOR)

        opaque_cells = collect_opaque_cells(players, enemies, exclude_player_name=active_player.name)
        current_visible_cells = compute_visible_cells(active_player.cell, door_states, opaque_cells)

        board.draw()
        if args.debug and los_debug_overlay and not reveal_all:
            draw_unseen_cells_overlay(screen, board, current_visible_cells)
        draw_solid_rock_overlay(screen, board, solid_rock_cells)
        draw_objects_on_board(screen, board, object_definitions, object_sprites, visible_objects, reveal_all)
        draw_doors_on_board(screen, board, door_states, door_sprites, visible_doors, reveal_all, secret_door_keys, secret_door_reveal_times)
        draw_move_options(screen, board, turn_state["reachable_cells"])
        active_player_name = players[active_player_index].name
        attackable_enemy_indexes = set(turn_state["attack_candidates"]) if turn_state["mode"] == "attack_target" else set()
        draw_enemies_on_board(
            screen,
            board,
            enemies,
            enemy_icons,
            visible_enemies,
            reveal_all,
            attackable_enemy_indexes,
        )
        draw_players_on_board(screen, board, players, board_icons, active_player_name)

        mouse_pos = pygame.mouse.get_pos()
        hovered_door = hovered_door_at_cursor(mouse_pos, board, door_states, door_sprites, visible_doors, reveal_all)
        if hovered_door is None:
            hovered_cell = board.px_to_cell(*mouse_pos)
            if hovered_cell is not None:
                col, row = hovered_cell
                board.draw_hover_cell(mouse_pos)
        else:
            draw_hovered_door_highlight(screen, board, hovered_door, door_states, door_sprites)
        visible_enemy_rows = build_enemy_menu_rows(
            enemies,
            enemy_icons,
            visible_enemies,
            reveal_all,
        )
        tooltip, controls_y = draw_left_menu(
            screen,
            panel_rect,
            mouse_pos,
            players,
            menu_icons,
            active_player_name,
            visible_enemy_rows,
            title_font,
            text_font,
            zargon_acting_enemy_name=(
                enemies[zargon_state["current_enemy_idx"]].get("name")
                if zargon_state is not None
                and zargon_state.get("current_enemy_idx") is not None
                and zargon_state["current_enemy_idx"] < len(enemies)
                else None
            ),
        )

        # Remove enemies whose death animation finished. Do this before
        # drawing UI controls so rect indices remain stable within a frame.
        now = pygame.time.get_ticks()
        expired: list[int] = []
        for idx, enemy in enumerate(enemies):
            if enemy.get("dying"):
                start = int(enemy.get("death_start", 0))
                if now - start >= DEATH_ANIM_MS:
                    expired.append(idx)
        if expired:
            for idx in reversed(expired):
                # remove enemy and its icon
                del enemies[idx]
                del enemy_icons[idx]
                visible_enemies = { (i - 1 if i > idx else i) for i in visible_enemies if i != idx }
        # Also purge dead players (if any are scheduled)
        expired_players: list[int] = []
        for pidx, player in enumerate(players):
            if getattr(player, "dying", False):
                start = int(getattr(player, "death_start", 0))
                if now - start >= DEATH_ANIM_MS:
                    expired_players.append(pidx)
        if expired_players:
            for pidx in reversed(expired_players):
                pname = players[pidx].name
                del players[pidx]
                # remove associated icons
                menu_icons.pop(pname, None)
                board_icons.pop(pname, None)
                # adjust active player index if necessary
                if active_player_index >= len(players):
                    active_player_index = max(0, len(players) - 1)

        # Draw movement dice at the BOTTOM of the left menu panel so they
        # appear anchored to the menu. Controls (buttons) keep their
        # normal placement (we don't alter their spacing here).
        controls_start_y = controls_y + 12
        movement_dice_height = 0
        show_dice_roll = turn_state["mode"] == "move"
        if show_dice_roll and turn_state.get("dice_roll"):
            die_one = pygame.transform.smoothscale(
                dice_faces[turn_state["dice_roll"][0]],
                (
                    dice_faces[turn_state["dice_roll"][0]].get_width() * 2,
                    dice_faces[turn_state["dice_roll"][0]].get_height() * 2,
                ),
            )
            die_two = pygame.transform.smoothscale(
                dice_faces[turn_state["dice_roll"][1]],
                (
                    dice_faces[turn_state["dice_roll"][1]].get_width() * 2,
                    dice_faces[turn_state["dice_roll"][1]].get_height() * 2,
                ),
            )
            # Random rotations (if present) and center dice horizontally
            rotations = turn_state.get("dice_rotations", [0, 0])
            r1 = rotations[0] if len(rotations) > 0 else 0
            r2 = rotations[1] if len(rotations) > 1 else 0
            rot_one = pygame.transform.rotate(die_one, r1)
            rot_two = pygame.transform.rotate(die_two, r2)
            gap = 10
            total_w = rot_one.get_width() + gap + rot_two.get_width()
            start_x = panel_rect.x + (panel_rect.width - total_w) // 2
            margin = 12
            die_y = panel_rect.bottom - margin - max(rot_one.get_height(), rot_two.get_height())
            die_one_rect = rot_one.get_rect(topleft=(start_x, die_y))
            die_two_rect = rot_two.get_rect(topleft=(die_one_rect.right + gap, die_y))
            screen.blit(rot_one, die_one_rect)
            screen.blit(rot_two, die_two_rect)
            # Controls spacing shouldn't change since dice are anchored to
            # the bottom of the menu, so leave movement_dice_height as 0.

        control_rects, controls_area_rect = draw_turn_controls(
            screen,
            panel_rect,
            controls_start_y,
            mouse_pos,
            players[active_player_index],
            turn_state,
            dice_faces,
            0,
            bool(adjacent_enemy_indexes(active_player.cell, enemies, door_states)),
            turn_state["attack_dialog"] is not None,
            title_font,
            text_font,
            zargon_active=zargon_state is not None,
        )
        if turn_state["attack_dialog"] is not None:
            target_index = int(turn_state["attack_dialog"]["target_index"])
            if 0 <= target_index < len(enemies):
                draw_attack_dialog(
                    screen,
                    turn_state["attack_dialog"],
                    active_player,
                    enemies[target_index],
                    menu_icons[active_player.name],
                    enemy_icons[target_index],
                    combat_face_sprites,
                    title_font,
                    text_font,
                    board,
                )
        # Render Zargon's (enemy→hero) attack dialog when it's active.
        if zargon_state is not None and zargon_state.get("attack_dialog") is not None:
            zdialog = zargon_state["attack_dialog"]
            enemy_idx = int(zdialog.get("enemy_index", 0))
            hero_idx = int(zdialog.get("defender_index", 0))
            if (
                0 <= enemy_idx < len(enemies)
                and 0 <= hero_idx < len(players)
            ):
                hero = players[hero_idx]
                enemy = enemies[enemy_idx]
                # Build a pseudo-dict for the hero so draw_attack_dialog can render
                # it in the "defender" column (which expects a dict).
                hero_as_dict = {
                    "name": hero.name,
                    "display_name": hero.name,
                    "attack_dice": hero.attack_dice,
                    "defense_dice": hero.defense_dice,
                    "hp": hero.hp,
                    "max_hp": hero.max_hp,
                }
                # Use a display dialog that wraps zargon's dialog fields into the
                # expected format for draw_attack_dialog.
                display_dialog = {
                    "outcome": zdialog["outcome"],
                    "phase": zdialog.get("phase", 0),
                    "attacker_rotations": zdialog.get("attacker_rotations", []),
                    "defender_rotations": zdialog.get("defender_rotations", []),
                    "target_index": enemy_idx,  # kept for compat
                }
                attacker_icon = zdialog.get("attacker_icon") or (
                    enemy_icons[enemy_idx] if enemy_idx < len(enemy_icons) else pygame.Surface((44, 44))
                )
                defender_icon = zdialog.get("defender_icon") or menu_icons.get(hero.name, pygame.Surface((44, 44)))
                draw_attack_dialog(
                    screen,
                    display_dialog,
                    enemy,           # enemy dict as "attacker"
                    hero_as_dict,    # hero dict as "defender"
                    attacker_icon,
                    defender_icon,
                    combat_face_sprites,
                    title_font,
                    text_font,
                    board,
                    auto_advance=True,
                )
        if tooltip:
            draw_tooltip(screen, mouse_pos, tooltip, text_font)
        draw_panel_transition(screen, panel_rect, panel_transition)

        pygame.display.flip()

    if audio_mod.audio_enabled:
        pygame.mixer.music.stop()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())