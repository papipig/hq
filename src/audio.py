from __future__ import annotations

import pathlib
import random
from typing import Optional

import pygame

SRC_DIR = pathlib.Path(__file__).parent
ASSETS_DIR = SRC_DIR.parent / "assets"
SFX_DIR = ASSETS_DIR / "audio" / "sfx"
MUSIC_DIR = ASSETS_DIR / "audio" / "music"


# Module-level audio state
audio_enabled: bool = False
sounds_enabled: bool = True
music_enabled: bool = True
sfx: dict[str, pygame.mixer.Sound] = {}
music_tracks: list[pathlib.Path] = []
current_music_track: Optional[pathlib.Path] = None
_sound_cache: dict[pathlib.Path, pygame.mixer.Sound] = {}


def load_sound(path: pathlib.Path) -> Optional[pygame.mixer.Sound]:
    if not path.exists():
        return None
    try:
        return pygame.mixer.Sound(str(path))
    except pygame.error:
        return None


def init_audio(cfg: dict) -> None:
    """Initialize audio subsystem and preload SFX/music list.

    This function intentionally does not abort on failure; callers should
    handle audio_enabled state gracefully.
    """
    global audio_enabled, sounds_enabled, music_enabled, sfx, music_tracks, current_music_track

    audio_enabled = True
    try:
        pygame.mixer.init()
    except pygame.error:
        audio_enabled = False

    sounds_enabled = bool(cfg.get("SOUNDS", True))
    music_enabled = bool(cfg.get("MUSIC", True))

    sfx = {}
    music_tracks = []
    current_music_track = None

    if audio_enabled:
        sfx = {
            "click": load_sound(SFX_DIR / "click.wav"),
            "dice_roll": load_sound(SFX_DIR / "dice_roll.mp3"),
            "door_open": load_sound(SFX_DIR / "door_open.mp3"),
            "move": load_sound(SFX_DIR / "move.mp3"),
        }
        music_tracks = [
            track
            for track in sorted(MUSIC_DIR.iterdir())
            if track.is_file() and track.suffix.lower() in {".mp3", ".wav", ".ogg"}
        ]


def play_sfx(effect_name: str) -> None:
    if not audio_enabled or not sounds_enabled:
        return
    sound = sfx.get(effect_name)
    if sound is not None:
        sound.play()


def play_named_sound(file_name: str) -> None:
    if not audio_enabled or not sounds_enabled or not file_name:
        return
    sound_path = SFX_DIR / file_name
    sound = _sound_cache.get(sound_path)
    if sound is None:
        sound = load_sound(sound_path)
        if sound is None:
            return
        _sound_cache[sound_path] = sound
    sound.play()


def play_random_music_track() -> None:
    global current_music_track
    if not audio_enabled or not music_enabled or not music_tracks:
        return
    choices = [track for track in music_tracks if track != current_music_track] or music_tracks
    selected = random.choice(choices)
    try:
        pygame.mixer.music.load(str(selected))
        pygame.mixer.music.play()
        current_music_track = selected
    except pygame.error:
        return
