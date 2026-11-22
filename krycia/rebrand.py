#!/usr/bin/env python3
"""
Rebranding Krycia pour RustDesk.

A lancer depuis la racine du dépôt RustDesk (fork) :
    python krycia/rebrand.py

Lit krycia/krycia.json, krycia/icone.png et krycia/logo.png, puis modifie le code source pour :
  - pointer vers TON serveur (ID + relais) avec TA clé publique ;
  - renommer l'application (fenêtres, service Windows, dossier de config) ;
  - remplacer les icônes et le logo ;
  - masquer les réglages serveur et couper la vérification de mises à jour RustDesk.

Le script est idempotent : on peut le relancer sans risque.
Il s'arrête avec une erreur claire si le code de RustDesk a changé
et qu'un motif n'est plus trouvé (plutôt que de compiler un client à moitié rebrandé).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
KRYCIA = Path(__file__).resolve().parent
CONF_FILE = KRYCIA / "krycia.json"
LOGO_FILE = KRYCIA / "logo.png"    # logo complet (large), affiché dans l'interface
ICON_FILE = KRYCIA / "icone.png"   # icône carrée (barre des tâches, raccourci, .exe)

errors: list[str] = []


def load_conf() -> dict:
    conf = json.loads(CONF_FILE.read_text(encoding="utf-8"))
    server = conf.get("serveur", "").strip()
    key = conf.get("cle_publique", "").strip()
    if key.startswith("COLLE_ICI"):
        key = ""
    if bool(server) != bool(key):
        sys.exit("krycia.json : renseigne 'serveur' ET 'cle_publique', ou laisse les deux vides "
                 "pour utiliser les serveurs publics RustDesk.")
    if key and not re.fullmatch(r"[A-Za-z0-9+/]{43}=", key):
        sys.exit(f"krycia.json : la clé publique '{key}' ne ressemble pas à une clé RustDesk "
                 "(44 caractères terminés par '=').")
    conf["serveur"], conf["cle_publique"] = server, key
    name = conf.get("nom_application", "KryciaDesk")
    if not re.fullmatch(r"[A-Za-z0-9-]+", name):
        sys.exit("krycia.json : 'nom_application' ne doit contenir que lettres, chiffres et tirets "
                 "(pas d'espace : il sert aussi de nom de service Windows).")
    if name.lower() == "rustdesk":
        sys.exit("krycia.json : choisis un nom différent de RustDesk.")
    return conf


def rs(s: str) -> str:
    """Echappe une valeur pour un littéral Rust/C/Dart entre guillemets."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def patch(rel: str, rules: list[tuple[str, str]], *, flags=re.M) -> None:
    path = ROOT / rel
    if not path.exists():
        errors.append(f"{rel} : fichier introuvable")
        return
    text = path.read_text(encoding="utf-8")
    orig = text
    for pattern, repl in rules:
        new, n = re.subn(pattern, lambda m, r=repl: m.expand(r), text, flags=flags)
        if n == 0:
            errors.append(f"{rel} : motif introuvable -> {pattern}")
        text = new
    if text != orig:
        path.write_text(text, encoding="utf-8", newline="")
        print(f"  ok  {rel}")
    else:
        print(f"  =   {rel} (déjà à jour)")


def rust_map(pairs: dict[str, str]) -> str:
    items = ", ".join(f'("{rs(k)}".to_owned(), "{rs(v)}".to_owned())' for k, v in pairs.items())
    # vec! et non [..] : hbb_common est en édition 2018 (into_iter sur tableau = références)
    return f"RwLock::new(vec![{items}].into_iter().collect())"


def main() -> None:
    if not (ROOT / "libs/hbb_common/src/config.rs").exists():
        sys.exit("Lance ce script depuis la racine du dépôt RustDesk, sous-modules inclus "
                 "(git submodule update --init).")
    c = load_conf()
    name = c.get("nom_application", "KryciaDesk")
    company = c.get("entreprise", "Krycia Informatique")
    desc = c.get("description", f"{name} - Assistance à distance")
    copy = c.get("copyright", f"Copyright © {company}. Basé sur RustDesk (AGPL-3.0).")
    color = c.get("couleur_principale", "#1565D8").lstrip("#").upper()
    if not re.fullmatch(r"[0-9A-F]{6}", color):
        sys.exit("krycia.json : 'couleur_principale' doit être au format #RRGGBB")

    print(f"Rebranding -> {name}  |  serveur {c['serveur'] or 'publics RustDesk'}")

    builtin = {}
    if c.get("masquer_reglages_serveur", True):
        builtin["hide-server-settings"] = "Y"
    local_defaults = {}
    if c.get("desactiver_mises_a_jour_rustdesk", True):
        local_defaults["enable-check-update"] = "N"

    # 1. Coeur : serveur, clé, nom, organisation, réglages intégrés
    cfg_rules = []
    if c["serveur"]:
        cfg_rules += [
            (r'(pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[)[^\]]*(\];)',
             rf'\g<1>"{rs(c["serveur"])}"\g<2>'),
            (r'(pub const RS_PUB_KEY: &str = ")[^"]*(";)', rf'\g<1>{c["cle_publique"]}\g<2>'),
        ]
    cfg_rules += [
        (r'(pub static ref APP_NAME: RwLock<String> = RwLock::new\(")[^"]*(")', rf'\g<1>{name}\g<2>'),
        # ORG volontairement inchangé (com.carriez) : sur Mac, install.scpt et macos.rs
        # utilisent "com.carriez" en dur pour les plists et le dossier de préférences.
    ]
    if builtin:
        cfg_rules.append((
            r'(pub static ref BUILTIN_SETTINGS: RwLock<HashMap<String, String>> = )[^;]*;',
            r'\g<1>' + rust_map(builtin).replace("\\", "\\\\") + ";"))
    if local_defaults:
        cfg_rules.append((
            r'(pub static ref DEFAULT_LOCAL_SETTINGS: RwLock<HashMap<String, String>> = )[^;]*;',
            r'\g<1>' + rust_map(local_defaults).replace("\\", "\\\\") + ";"))
    patch("libs/hbb_common/src/config.rs", cfg_rules)

    # 2. Métadonnées des .exe (Propriétés > Détails sous Windows)
    for cargo in ("Cargo.toml", "libs/portable/Cargo.toml"):
        patch(cargo, [
            (r'^(description = ")[^"]*(")', rf'\g<1>{rs(desc)}\g<2>'),
            (r'^(LegalCopyright = ")[^"]*(")', rf'\g<1>{rs(copy)}\g<2>'),
            (r'^(ProductName = ")[^"]*(")', rf'\g<1>{name}\g<2>'),
            (r'^(FileDescription = ")[^"]*(")', rf'\g<1>{rs(desc)}\g<2>'),
        ])
    patch("flutter/windows/runner/Runner.rc", [
        (r'(VALUE "CompanyName", ")[^"]*(")', rf'\g<1>{rs(company)}\g<2>'),
        (r'(VALUE "FileDescription", ")[^"]*(")', rf'\g<1>{rs(desc)}\g<2>'),
        (r'(VALUE "LegalCopyright", ")[^"]*(")', rf'\g<1>{rs(copy)}\g<2>'),
        (r'(VALUE "ProductName", ")[^"]*(")', rf'\g<1>{name}\g<2>'),
    ])

    # 3. Titre de fenêtre par défaut + barre d'onglets
    patch("flutter/windows/runner/main.cpp", [
        (r'(std::wstring app_name = L")[^"]*(";)', rf'\g<1>{name}\g<2>'),
    ])
    patch("flutter/lib/desktop/widgets/tabbar_widget.dart", [
        (rf'(const Text\(\s*")(?:RustDesk|{name})(",)', rf'\g<1>{name}\g<2>'),
    ])

    # 4. macOS : nom du bundle (.app), copyright, chemins de build
    patch("flutter/macos/Runner/Configs/AppInfo.xcconfig", [
        (r'^(PRODUCT_NAME = ).*$', rf'\g<1>{name}'),
        (r'^(PRODUCT_COPYRIGHT = ).*$', rf'\g<1>{copy}'),
    ])
    patch("flutter/macos/Runner.xcodeproj/project.pbxproj", [
        (rf'\b(?:RustDesk|{name})\.app\b', f'{name}.app'),
    ])
    patch("build.py", [
        (rf'(Products/Release/)(?:RustDesk|{name})(\.app/Contents/MacOS/)', rf'\g<1>{name}\g<2>'),
    ])

    # 5. Couleur d'accent de l'interface
    patch("flutter/lib/common.dart", [
        (r'(static const Color accent = Color\(0xFF)[0-9A-Fa-f]{6}(\);)', rf'\g<1>{color}\g<2>'),
    ])

    # 6. Icônes et logo
    make_icons()

    if errors:
        print("\nERREURS - le code RustDesk a probablement changé :", file=sys.stderr)
        for e in errors:
            print("  - " + e, file=sys.stderr)
        sys.exit(1)
    print("\nRebranding terminé.")


def make_icons() -> None:
    icon_src = ICON_FILE if ICON_FILE.exists() else LOGO_FILE
    if not icon_src.exists():
        print("  !   krycia/icone.png et logo.png absents : icônes RustDesk conservées")
        return
    try:
        from PIL import Image
    except ImportError:
        sys.exit("Pillow manquant : pip install pillow")
    src = Image.open(icon_src).convert("RGBA")
    # carré centré, sans déformer
    side = max(src.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(src, ((side - src.width) // 2, (side - src.height) // 2))

    def png(rel: str, size: int) -> None:
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        sq.resize((size, size), Image.LANCZOS).save(p)
        print(f"  ok  {rel}")

    def ico(rel: str, sizes: list[int]) -> None:
        p = ROOT / rel
        sq.resize((256, 256), Image.LANCZOS).save(p, format="ICO", sizes=[(s, s) for s in sizes])
        print(f"  ok  {rel}")

    full = [16, 24, 32, 48, 64, 128, 256]
    ico("res/icon.ico", full)
    ico("res/tray-icon.ico", [16, 24, 32])
    ico("flutter/windows/runner/resources/app_icon.ico", full)
    png("res/icon.png", 1024)
    png("res/32x32.png", 32)
    png("res/64x64.png", 64)
    png("res/128x128.png", 128)
    png("res/128x128@2x.png", 256)
    png("flutter/assets/icon.png", 256)  # petite icône de la barre d'onglets
    icns = ROOT / "flutter/macos/Runner/AppIcon.icns"
    sq.resize((1024, 1024), Image.LANCZOS).save(icns, format="ICNS")
    print("  ok  flutter/macos/Runner/AppIcon.icns")

    # Logo de la page d'accueil : on garde les proportions (logo large accepté)
    if LOGO_FILE.exists():
        logo = Image.open(LOGO_FILE).convert("RGBA")
        logo = logo.crop(logo.getbbox() or (0, 0, *logo.size))
        w = 600
        logo = logo.resize((w, max(1, round(logo.height * w / logo.width))), Image.LANCZOS)
        logo.save(ROOT / "flutter/assets/logo.png")
        print("  ok  flutter/assets/logo.png")


if __name__ == "__main__":
    main()
