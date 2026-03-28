from __future__ import annotations

from dataclasses import dataclass
import json
import pathlib

import pygame

SRC_DIR = pathlib.Path(__file__).parent
DATA_FILE = SRC_DIR.parent / "data" / "characters.json"
SPRITES_DIR = SRC_DIR.parent / "assets" / "graphics" / "sprites"
HERO_NAMES = {"barbarian", "dwarf", "elf", "wizard"}


@dataclass(slots=True)
class PlayerClass:
    name: str
    hp: int
    max_hp: int
    attack_dice: int
    defense_dice: int
    mind: int
    icon_file: str
    color: tuple[int, int, int]
    cell: tuple[int, int]
    dying: bool = False
    death_start: int = 0

    def icon_path(self) -> pathlib.Path:
        return SPRITES_DIR / self.icon_file

    @classmethod
    def from_dict(cls, data: dict) -> "PlayerClass":
        raw_cell = data.get("cell", [0, 0])
        return cls(
            name=str(data["name"]),
            hp=int(data["hp"]),
            max_hp=int(data.get("max_hp", data["hp"])),
            attack_dice=int(data["attack_dice"]),
            defense_dice=int(data["defense_dice"]),
            mind=int(data["mind"]),
            icon_file=str(data["icon_file"]),
            color=tuple(data["color"]),
            cell=(int(raw_cell[0]), int(raw_cell[1])),
        )

def load_players() -> list[PlayerClass]:
    with DATA_FILE.open() as file:
        payload = json.load(file)
    raw_characters = payload.get("heroes", [])
    if payload.get("enemies"):
        return [PlayerClass.from_dict(item) for item in raw_characters]

    # Backward-compatible mode: characters contains both heroes and monsters.
    hero_rows = [
        item for item in raw_characters
        if str(item.get("name", "")).strip().lower() in HERO_NAMES
    ]
    return [PlayerClass.from_dict(item) for item in hero_rows]


def load_enemies() -> list[dict]:
    with DATA_FILE.open() as file:
        payload = json.load(file)
    explicit_enemies = payload.get("enemies")
    if explicit_enemies:
        return explicit_enemies


def load_player_icon(player: PlayerClass, size: int, font: pygame.font.Font) -> pygame.Surface:
    path = player.icon_path()
    if path.exists():
        raw = pygame.image.load(str(path)).convert()
        return pygame.transform.smoothscale(raw, (size, size))

    surface = pygame.Surface((size, size))
    surface.fill(player.color)
    label = font.render(player.name[0], True, (245, 240, 230))
    label_rect = label.get_rect(center=(size // 2, size // 2))
    surface.blit(label, label_rect)
    return surface
