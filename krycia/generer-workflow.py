#!/usr/bin/env python3
"""
Génère .github/workflows/krycia-windows.yml à partir du workflow officiel
.github/workflows/flutter-build.yml de RustDesk (Windows x64 uniquement),
en y ajoutant l'étape de rebranding Krycia.

A relancer depuis la racine du dépôt après chaque mise à jour du fork :
    python krycia/generer-workflow.py
"""
import json
import re
import sys
from pathlib import Path

SRC = Path(".github/workflows/flutter-build.yml")
DST = Path(".github/workflows/krycia-windows.yml")

if not SRC.exists():
    sys.exit("Lance ce script depuis la racine du dépôt RustDesk.")
lines = SRC.read_text(encoding="utf-8").splitlines()
APP = json.loads(Path("krycia/krycia.json").read_text(encoding="utf-8")).get("nom_application", "KryciaDesk")


def find(pred, start=0, what=""):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    sys.exit(f"flutter-build.yml : repère introuvable ({what}). Le workflow officiel a changé.")


def job_block(name):
    s = find(lambda l: l == f"  {name}:", what=name)
    e = find(lambda l: re.match(r"^  [A-Za-z0-9_-]+:$", l) is not None, s + 1, "job suivant")
    return lines[s:e]


# --- env officiel (versions de Flutter, vcpkg, etc.) ---
env_s = find(lambda l: l == "env:", what="env")
env_e = find(lambda l: l == "jobs:", env_s, "jobs")
env = [l for l in lines[env_s + 1:env_e]
       if not re.match(r"^  (TAG_NAME|UPLOAD_ARTIFACT|PUBLISH_UPDATE_METADATA|SIGN_BASE_URL|"
                       r"ANDROID_SIGNING_KEY|MACOS_P12_BASE64):", l)]


def drop_matrix_entry(block, marker):
    """Supprime l'entrée '- { ... }' de la matrice qui contient `marker` (ex. ARM64)."""
    out, i = [], 0
    while i < len(block):
        if re.match(r"^\s*- \{\s*$", block[i]):
            j = i
            while not re.match(r"^\s*\}\s*$", block[j]):
                j += 1
            entry = block[i:j + 1]
            if not any(marker in l for l in entry):
                out += entry
            i = j + 1
        else:
            out.append(block[i])
            i += 1
    return out


def strip_needs_validate(block):
    return [l for l in block if l.strip() != "needs: [validate-update-metadata-keys]"]


bridge = strip_needs_validate(job_block("generate-bridge"))
topmost = drop_matrix_entry(strip_needs_validate(job_block("build-RustDeskTempTopMostWindow")),
                            "windows-11-arm")
win = drop_matrix_entry(job_block("build-for-windows-flutter"), "aarch64-pc-windows-msvc")

# Étape de rebranding juste après le checkout
co = next(i for i, l in enumerate(win) if l.strip() == "- name: Checkout source code")
end = co + 1
while end < len(win) and not win[end].strip().startswith("- name:"):
    end += 1
rebrand = [
    "      - name: Appliquer la marque Krycia",
    "        shell: bash",
    "        run: |",
    "          pip3 install pillow",
    "          python3 krycia/rebrand.py",
    "",
]
win = win[:end] + rebrand + win[end:]

# On garde tout jusqu'à « Build self-extracted executable » inclus, sans les étapes de signature
# RustDesk (secrets officiels), puis on ajoute nos étapes de sortie.
keep, skip = [], False
names_to_skip = (
    "Sign rustdesk files", "Verify Windows Flutter version", "Verify template payload signatures",
    "Build template packer", "Upload unsigned template packer",
)
cut = next(i for i, l in enumerate(win) if l.strip() == "- name: Add MSBuild to PATH")
for l in win[:cut]:
    m = re.match(r"^      - name: (.*)$", l)
    if m:
        skip = m.group(1).strip() in names_to_skip
    if not skip:
        keep.append(l)
win = keep
win = [l.replace("./SignOutput/rustdesk-${{ env.VERSION }}",
                 "./SignOutput/${{ env.APP_FILE }}-${{ env.VERSION }}") for l in win]
win += [
    "      - name: Publier le .exe Krycia (artefact)",
    "        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1",
    "        with:",
    "          name: ${{ env.APP_FILE }}-windows-x64",
    "          path: ./SignOutput/*.exe",
    "          if-no-files-found: error",
    "",
    "      - name: Publier une release GitHub",
    "        uses: softprops/action-gh-release@de2c0eb89ae2a093876385947365aca7b0e5f844 # v1",
    "        with:",
    "          prerelease: false",
    "          tag_name: ${{ env.TAG_NAME }}",
    "          name: ${{ env.APP_FILE }} ${{ env.VERSION }}",
    "          files: ./SignOutput/*.exe",
    "",
]

header = f"""# ---------------------------------------------------------------------------
# {APP} - compilation Windows x64
# Généré par krycia/generer-workflow.py à partir de flutter-build.yml (RustDesk).
# Lancement : onglet Actions > "{APP} - Windows" > Run workflow.
# Durée : ~45-70 min. Résultat : artefact + release "krycia".
# ---------------------------------------------------------------------------
name: {APP} - Windows

on:
  workflow_dispatch:
    inputs:
      upload-artifact:
        type: boolean
        default: true

permissions:
  contents: write

env:
  TAG_NAME: "krycia"
  APP_FILE: "{APP}"
  UPLOAD_ARTIFACT: "true"
  PUBLISH_UPDATE_METADATA: "false"
  SIGN_BASE_URL: "-2"
"""
out = header + "\n".join(env) + "\n\njobs:\n" + "\n".join(bridge + topmost + win) + "\n"
DST.write_text(out, encoding="utf-8", newline="\n")
print(f"{DST} généré ({len(out.splitlines())} lignes).")
