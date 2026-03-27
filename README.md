# HQ

![HeroQuest box art](assets/graphics/ui/box.jpg)

Unofficial Python and pygame project for a HeroQuest-style dungeon crawler.

![HeroQuest box art](assets/graphics/misc/demo.png)

## Project Layout

```text
hq/
├── assets/
│   ├── audio/
│   │   ├── music/
│   │   └── sfx/
│   ├── fonts/
│   └── graphics/
│       ├── sprites/
│       ├── tiles/
│       └── ui/
├── data/
│   ├── maps/
│   └── quests/
├── docs/
├── src/
└── tests/
```

## Quick Start

1. Create a virtual environment.
2. Install the project in editable mode.
3. Run the prototype window.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
hq-game
```

You can also start it with:

```bash
python -m main
```

## Notes

- Put sound effects and music in `assets/audio/`.
- Put sprites, tiles, and interface graphics in `assets/graphics/`.
- Put quest definitions and map data in `data/`.
- Put design notes and source tracking for assets in `docs/`.

## Disclaimer

This repository is an unofficial fan project and prototype. It is not owned by, approved by, endorsed by, sponsored by, or affiliated with Hasbro, Avalon Hill, HeroQuest, Milton Bradley, Games Workshop, Stephen Baker, or the original creators and publishers of HeroQuest.

The HeroQuest name and related franchise elements are protected by copyright, trademark, and other intellectual property laws and belong to their respective rights holders. Current HeroQuest branding is associated with Hasbro and Avalon Hill, while the original 1989 board game was published by Milton Bradley in cooperation with Games Workshop.

Original code in this repository is separate from the HeroQuest intellectual property and is distributed under the license in this project.

## Thanks to

Thanks to `https://forum.yeoldeinn.com`, and `https://github.com/hghero/HeroQuest` for inspiration (and also I took the liberty to take graphics from them).