from __future__ import annotations

from dataclasses import dataclass
import json
import pathlib

import pygame

SRC_DIR = pathlib.Path(__file__).parent
DATA_FILE = SRC_DIR.parent / "data" / "objects.json"


@dataclass(slots=True)
class ObjectPlacement:
    col: int
    row: int
    size: tuple[int, int]
    rotation: int = 0


@dataclass(slots=True)
class GameObjectDefinition:
    object_id: str
    size: tuple[int, int]
    image_path: str
    passthrough: bool
    placements: list[ObjectPlacement]

    def image_file(self) -> pathlib.Path:
        return (SRC_DIR.parent / self.image_path).resolve()

    @classmethod
    def from_dict(cls, data: dict) -> "GameObjectDefinition":
        raw_size = data.get("size", [1, 1])
        width = max(1, int(raw_size[0]))
        height = max(1, int(raw_size[1]))
        raw_placements = data.get("placements", [])
        placements = [
            ObjectPlacement(int(position[0]), int(position[1]), (width, height))
            for position in raw_placements
        ]
        return cls(
            object_id=str(data["id"]),
            size=(width, height),
            image_path=str(data["image"]),
            passthrough=bool(data.get("passthrough", False)),
            placements=placements,
        )


def load_object_definitions() -> list[GameObjectDefinition]:
    if not DATA_FILE.exists():
        return []
    with DATA_FILE.open() as file:
        payload = json.load(file)
    return [GameObjectDefinition.from_dict(item) for item in payload.get("objects", [])]


def load_object_sprite(
    definition: GameObjectDefinition,
    cell_size: int,
    font: pygame.font.Font,
    size: tuple[int, int] | None = None,
    rotation: int = 0,
    fill_ratio: float = 0.9,
) -> pygame.Surface:
    placed_size = size or definition.size
    footprint_w = max(1, placed_size[0] * cell_size)
    footprint_h = max(1, placed_size[1] * cell_size)
    safe_ratio = max(0.1, min(1.0, fill_ratio))
    width = max(1, int(round(footprint_w * safe_ratio)))
    height = max(1, int(round(footprint_h * safe_ratio)))
    image_file = definition.image_file()
    if image_file.exists():
        raw = pygame.image.load(str(image_file)).convert_alpha()
        quarter_turns = int(rotation) % 4
        if quarter_turns:
            raw = pygame.transform.rotate(raw, -90 * quarter_turns)
        return pygame.transform.smoothscale(raw, (width, height))

    placeholder = pygame.Surface((width, height), pygame.SRCALPHA)
    placeholder.fill((100, 78, 55, 205))
    pygame.draw.rect(placeholder, (210, 182, 130), placeholder.get_rect(), 2, border_radius=8)
    label = font.render(definition.object_id[:2].upper(), True, (250, 240, 220))
    placeholder.blit(label, label.get_rect(center=placeholder.get_rect().center))
    return placeholder
