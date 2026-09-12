#!/usr/bin/env python3
"""Structural manifest checks for Agentik, runnable without the noctalia CLI.

Verifies:
  1. plugin.toml parses as TOML, uses Noctalia's MAJOR.MINOR.PATCH version
     contract, and translations/en.json parses as JSON.
  2. Every label_key/description_key referenced by the manifest exists in en.json.
  3. Every [[setting.options]] entry declares value + label_key.
  4. Every setting read via noctalia.getConfig("...") or configured_bool("...")
     in the Luau scripts is declared somewhere in plugin.toml.
  5. Every translation key used via noctalia.tr("...")/trp("...") exists in en.json
     (trp resolves "<key>.one"/"<key>.other" for plurals).
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GETCONFIG = re.compile(r'(?:getConfig|configured_bool)\(\s*"([^"]+)"')
TRANSKEY = re.compile(r'noctalia\.(tr|trp)\(\s*"([^"]+)"')
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def fail(message: str) -> None:
    print(f"check_manifest: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    manifest = tomllib.loads((ROOT / "plugin.toml").read_text(encoding="utf-8"))
    translations = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))
    version = manifest.get("version")
    if not isinstance(version, str) or SEMVER.fullmatch(version) is None:
        fail("plugin version must use MAJOR.MINOR.PATCH (Noctalia does not accept prerelease suffixes)")


    settings: list[dict] = list(manifest.get("setting", []))
    for entry in ("widget", "desktop_widget", "panel", "service"):
        for host in manifest.get(entry, []):
            settings.extend(host.get("setting", []))

    declared: set[str] = set()
    translation_refs: list[str] = []
    for setting in settings:
        declared.add(setting["key"])
        translation_refs.append(setting["label_key"])
        translation_refs.append(setting["description_key"])
        for option in setting.get("options", []):
            if "value" not in option or "label_key" not in option:
                fail(f"setting '{setting['key']}' has an option missing value/label_key")
            translation_refs.append(option["label_key"])

    missing = sorted({ref for ref in translation_refs if ref not in translations})
    if missing:
        fail("translation keys missing from en.json: " + ", ".join(missing))

    used: set[str] = set()
    for script in ROOT.glob("*.luau"):
        used.update(GETCONFIG.findall(script.read_text(encoding="utf-8")))
    undeclared = sorted(used - declared)
    if undeclared:
        fail("settings read but not declared in plugin.toml: " + ", ".join(undeclared))

    trans_used: list[str] = []
    for script in ROOT.glob("*.luau"):
        trans_used.extend(
            key if fn == "tr" else f"{key}.one/{key}.other"
            for fn, key in TRANSKEY.findall(script.read_text(encoding="utf-8"))
        )
    missing_trans = sorted({
        variant
        for key in trans_used
        for variant in key.split("/")
        if variant not in translations
    })
    if missing_trans:
        fail("translation keys used but missing from en.json: " + ", ".join(missing_trans))
    print(
        f"check_manifest: ok ({len(declared)} declared settings, "
        f"{len(translation_refs)} translation refs, {len(used)} config reads, "
        f"{len(trans_used)} translation uses)"
    )


if __name__ == "__main__":
    main()
