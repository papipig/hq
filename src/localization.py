"""
localization.py — simple key-based translation system.

Usage
-----
    from localization import init_locale, t

    init_locale("fr")          # call once at startup, after reading config
    label = t("ui.move")       # returns "Déplacer"
    label = t("ui.move", "en") # force a specific locale (rare)

Keys are dot-separated strings.  Missing keys fall back to the English text
so that new strings added in English never cause KeyError before they are
translated.
"""

from __future__ import annotations

_current_locale: str = "en"

SUPPORTED_LOCALES: tuple[str, ...] = ("en", "fr")


def init_locale(lang: str) -> None:
    """Set the active locale.  Call once after loading config.json."""
    global _current_locale
    lang = lang.lower().strip()
    if lang not in SUPPORTED_LOCALES:
        print(f"[localization] unknown locale '{lang}', defaulting to 'en'")
        lang = "en"
    _current_locale = lang


def t(key: str, locale: str | None = None) -> str:
    """Return the translated string for *key* in the active locale.

    Falls back to English if the key is missing in the requested locale.
    Raises KeyError only when the key is missing in English too (dev mistake).
    """
    loc = (locale or _current_locale).lower()
    strings = _STRINGS.get(loc, _STRINGS["en"])
    if key in strings:
        return strings[key]
    # fallback
    if loc != "en" and key in _STRINGS["en"]:
        return _STRINGS["en"][key]
    # hard miss — return the key itself so the UI stays functional
    return key


def translate_name(name: str, *, prefix: str = "") -> str:
    """Translate a character or enemy name.

    Tries ``{prefix}.{name.lower()}`` first, then ``char.{name.lower()}``,
    then ``enemy.{name.lower()}``, finally returns *name* unchanged.

    Examples::

        translate_name("Barbarian")           # → t("char.barbarian")
        translate_name("Goblin", prefix="enemy")
    """
    lower = name.lower()
    candidates = []
    if prefix:
        candidates.append(f"{prefix}.{lower}")
    candidates += [f"char.{lower}", f"enemy.{lower}"]
    for key in candidates:
        result = t(key)
        if result != key:   # key was found (t() returns key on hard miss)
            return result
    return name   # untranslated fallback


# ---------------------------------------------------------------------------
# Translation tables
# ---------------------------------------------------------------------------

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # ── Sidebar headings ────────────────────────────────────────────────
        "sidebar.characters":       "Characters",
        "sidebar.enemies":          "Enemies",

        # ── Turn badges ─────────────────────────────────────────────────────
        "badge.turn":               "TURN",
        "badge.act":                "ACT",

        # ── Buttons ─────────────────────────────────────────────────────────
        "btn.move":                 "MOVE",
        "btn.action":               "ACTION",
        "btn.pass_turn":            "PASS TURN",

        # ── Action names (must match ACTIONS list upper-cased for comparison)
        "action.attack":            "ATTACK",
        "action.cast_spell":        "CAST SPELL",
        "action.search_treasure":   "SEARCH FOR TREASURE",
        "action.search_doors":      "SEARCH FOR SECRET DOORS",
        "action.search_traps":      "SEARCH FOR TRAPS",
        "action.disarm_trap":       "DISARM A TRAP",

        # ── Combat panel ────────────────────────────────────────────────────
        "combat.title":             "Combat",
        "combat.roll_attack":       "Click to roll attack dice",
        "combat.auto_rolling":      "Auto-rolling…",
        "combat.enemy_rolled":      "Enemy rolled {skulls} skull(s) — click to defend!",
        "combat.attacker_rolled":   "Attacker rolled {skulls} skull(s) — rolling defence…",
        "combat.result":            "Skulls {skulls}  vs  Saves {saves}  =>  Damage {damage}",
        "combat.click_attack":      "Click to attack",
        "combat.click_resolve":     "Click to resolve",
        "combat.waiting":           "…",

        # ── Status bar ──────────────────────────────────────────────────────
        "status.choose_move_action": "Choose MOVE or ACTION",
        "status.resolve_combat":     "Resolve combat",
        "status.choose_action":      "Choose an action",
        "status.select_enemy":       "Select an adjacent enemy",
        "status.action_used":        "Action used: {action}",

        # ── Zargon turn overlay ─────────────────────────────────────────────
        "zargon.heading":            "Zargon's Turn",
        "zargon.acting":             "Enemies are acting…",
        "hero.turn_heading":         "{name}'s Turn",

        # ── Tooltip stat labels ─────────────────────────────────────────────
        "tooltip.attack_dice":       "Attack dice: {value}",
        "tooltip.defense_dice":      "Defense dice: {value}",
        "tooltip.mind":              "Mind: {value}",
        "tooltip.body":              "Body: {current}/{maximum}",
        "tooltip.move":              "Move: {value}",

        # ── Game over screen ─────────────────────────────────────────────────
        "gameover.title":            "GAME OVER",
        "gameover.subtitle":         "Press any key or click to restart",

        # ── Hero names ───────────────────────────────────────────────────────
        "char.barbarian":            "Barbarian",
        "char.dwarf":                "Dwarf",
        "char.elf":                  "Elf",
        "char.wizard":               "Wizard",

        # ── Enemy names ──────────────────────────────────────────────────────
        "enemy.chaos warrior":       "Chaos Warrior",
        "enemy.fimir abomination":   "Fimir Abomination",
        "enemy.gargoyle":            "Gargoyle",
        "enemy.goblin archer":       "Goblin Archer",
        "enemy.goblin spearman":     "Goblin Spearman",
        "enemy.goblin":              "Goblin",
        "enemy.mummy":               "Mummy",
        "enemy.orc archer":          "Orc Archer",
        "enemy.orc spearman":        "Orc Spearman",
        "enemy.orc":                 "Orc",
        "enemy.skeleton archer":     "Skeleton Archer",
        "enemy.skeleton spearman":   "Skeleton Spearman",
        "enemy.skeleton":            "Skeleton",
        "enemy.zombie":              "Zombie",
        "enemy.zargon":              "Zargon",
    },

    "fr": {
        # ── Sidebar headings ────────────────────────────────────────────────
        "sidebar.characters":       "Personnages",
        "sidebar.enemies":          "Ennemis",

        # ── Turn badges ─────────────────────────────────────────────────────
        "badge.turn":               "TOUR",
        "badge.act":                "ACT",

        # ── Buttons ─────────────────────────────────────────────────────────
        "btn.move":                 "DÉPLACER",
        "btn.action":               "ACTION",
        "btn.pass_turn":            "PASSER",

        # ── Action names ────────────────────────────────────────────────────
        "action.attack":            "ATTAQUER",
        "action.cast_spell":        "LANCER UN SORT",
        "action.search_treasure":   "CHERCHER UN TRÉSOR",
        "action.search_doors":      "CHERCHER DES PORTES SECRÈTES",
        "action.search_traps":      "CHERCHER DES PIÈGES",
        "action.disarm_trap":       "DÉSAMORCER UN PIÈGE",

        # ── Combat panel ────────────────────────────────────────────────────
        "combat.title":             "Combat",
        "combat.roll_attack":       "Cliquer pour lancer les dés d'attaque",
        "combat.auto_rolling":      "Lancer automatique…",
        "combat.enemy_rolled":      "L'ennemi a obtenu {skulls} crâne(s) — cliquez pour défendre !",
        "combat.attacker_rolled":   "L'attaquant a obtenu {skulls} crâne(s) — lancer la défense…",
        "combat.result":            "Crânes {skulls}  vs  Boucliers {saves}  =>  Dégâts {damage}",
        "combat.click_attack":      "Cliquer pour attaquer",
        "combat.click_resolve":     "Cliquer pour résoudre",
        "combat.waiting":           "…",

        # ── Status bar ──────────────────────────────────────────────────────
        "status.choose_move_action": "Choisir DÉPLACER ou ACTION",
        "status.resolve_combat":     "Résoudre le combat",
        "status.choose_action":      "Choisir une action",
        "status.select_enemy":       "Sélectionner un ennemi adjacent",
        "status.action_used":        "Action utilisée : {action}",

        # ── Zargon turn overlay ─────────────────────────────────────────────
        "zargon.heading":            "Tour de Zargon",
        "zargon.acting":             "Les ennemis agissent…",
        "hero.turn_heading":         "Tour de {name}",

        # ── Tooltip stat labels ─────────────────────────────────────────────
        "tooltip.attack_dice":       "Dés d'attaque : {value}",
        "tooltip.defense_dice":      "Dés de défense : {value}",
        "tooltip.mind":              "Esprit : {value}",
        "tooltip.body":              "Corps : {current}/{maximum}",
        "tooltip.move":              "Déplacement : {value}",

        # ── Game over screen ─────────────────────────────────────────────────
        "gameover.title":            "PARTIE TERMINÉE",
        "gameover.subtitle":         "Appuyez sur une touche ou cliquez pour recommencer",

        # ── Hero names ───────────────────────────────────────────────────────
        "char.barbarian":            "Barbare",
        "char.dwarf":                "Nain",
        "char.elf":                  "Elfe",
        "char.wizard":               "Sorcier",

        # ── Enemy names ──────────────────────────────────────────────────────
        "enemy.chaos warrior":       "Guerrier du Chaos",
        "enemy.fimir abomination":   "Abomination Fimir",
        "enemy.gargoyle":            "Gargouille",
        "enemy.goblin archer":       "Archer Gobelin",
        "enemy.goblin spearman":     "Lancier Gobelin",
        "enemy.goblin":              "Gobelin",
        "enemy.mummy":               "Momie",
        "enemy.orc archer":          "Archer Orc",
        "enemy.orc spearman":        "Lancier Orc",
        "enemy.orc":                 "Orc",
        "enemy.skeleton archer":     "Archer Squelette",
        "enemy.skeleton spearman":   "Lancier Squelette",
        "enemy.skeleton":            "Squelette",
        "enemy.zombie":              "Zombie",
        "enemy.zargon":              "Zargon",
    },
}
