# CBZ → EPUB Converter — UI Preview (PyQt6)

Une application de démonstration (prototype UI) écrite en Python / PyQt6 qui rend des scènes exportées depuis Figma (format JSON) et orchestre un flux de conversion CBZ → EPUB via Calibre (`ebook-convert`). Le projet sert à valider visuellement les écrans et le parcours utilisateur avant d'implémenter une version production.

## Fonctionnalités

- Rendu pixel‑perfect de scènes Figma (JSON → widgets QLabel/QPushButton).
- Animations texte : frappe progressive (typing) et ellipses animées.
- Contrôles interactifs pour sélectionner les fichiers CBZ et le dossier de sortie EPUB.
- Champs éditables pour métadonnées (Auteur / Série) avec validation et navigation par Entrée.
- Pipeline de conversion en arrière-plan : réparation CBZ, extraction de la couverture et appel à `ebook-convert` (Calibre).
- Barres de progression lissées (animation d'interpolation côté UI).
- Zone de log qui écrit un `log.txt` dans le dossier de sortie et permet d'ouvrir/sélectionner le fichier sur Windows (bouton accessible sur l'écran final).
- Fenêtre sans barre native (frameless) avec zone de glisser dédiée dans la scène et boutons Min/Close stylisés.

## Prérequis

- Python 3.8+ (3.10 recommandé)
- PyQt6
- Calibre (assurez‑vous que `ebook-convert` est disponible dans le PATH)

Optionnel / Développement
- Git, un environnement virtuel (`python -m venv`) et un éditeur (VSCode, PyCharm...)

## Installation

1. Cloner le dépôt :

```pwsh
git clone https://github.com/Lucasribous/cbz-to-epub-converter.git
cd cbz-to-epub-converter
```

2. Créer et activer un environnement virtuel (PowerShell) :

```pwsh
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Installer les dépendances (créer un `requirements.txt` si besoin) :

```pwsh
pip install PyQt6
# Ajouter d'autres dépendances si tu les définis (ex: pytest pour les tests)
```

## Usage

Lancer l'application depuis la racine du projet :

```pwsh
python -u main.py
```

Comportement attendu : navigation entre les scènes Figma (situées dans `scene/`), sélection de fichiers `.cbz`, choix du dossier de sortie EPUB, saisie des métadonnées, et lancement de la conversion. La scène `08_working.json` affiche des barres de progression lissées pendant la conversion. À la fin, l'écran `09_end.json` affiche un bouton Log qui ouvre/sélectionne le `log.txt` créé dans le dossier de sortie.

## Structure du dépôt

- `main.py` — point d'entrée, orchestre les scènes et la conversion.
- `ui/` — code de rendu UI et parser JSON (ex: `ui/base_scene.py`).
- `scene/` — exports JSON des scènes Figma (01_Home.json, ... 09_end.json).
- `assets/` — images, icônes et polices utilisées par les scènes.
- `.gitignore` — règles d'ignorance pour l'environnement et les artefacts.

## Développement

- Pour ajouter une nouvelle scène Figma : exporter en JSON et placer le fichier dans `scene/`, puis recharger l'app.
- Les images référencées par le JSON doivent se trouver dans `assets/images/`.
- Police : le module charge automatiquement les polices trouvées dans `assets/fonts/`.

### Tests rapides

- Vérifier que les fichiers Python se compilent sans erreur :

```pwsh
python -m py_compile ui\base_scene.py
python -m py_compile main.py
```

## Debug & Logs

- Un log de session (`log.txt`) est généré dans le dossier de sortie EPUB à la fin d'une conversion et peut être ouvert via le bouton Log sur l'écran final.
- Fichier de debug global possible : `calibre-debug.log` (généré par Calibre si configuré).

## Limitations et notes

- Prototype UI / preview : conçu pour la validation visuelle et le prototypage — pas destiné à un déploiement production sans renforcement (gestion d'erreurs, sécurité, UI/UX, tests).
- La conversion repose sur Calibre (`ebook-convert`) — l'utilisateur doit l'installer séparément.
- Sur certaines plateformes, la transparence de fenêtre et les flags frameless peuvent dépendre du gestionnaire de fenêtres.

## Contribution

PRs et issues sont bienvenus. Suggestions utiles : ajouter des tests unitaires, config CI (lint/py_compile), packaging, et couverture de cas d'erreurs lors de la conversion.

## Licence

Proposé : MIT — créer un fichier `LICENSE` si tu veux appliquer cette licence.

---
## Packager en .exe (Windows)

Un script PowerShell `build_exe.ps1` est fourni pour créer un exécutable Windows via PyInstaller. Il rassemble les répertoires `scene/`, `assets/`, `ui/` et inclut le `README.md` dans le bundle.

Étapes rapides (PowerShell) :

```pwsh
# activer l'environnement
.\.venv\Scripts\Activate.ps1

# installer pyinstaller si nécessaire
python -m pip install --upgrade pip
python -m pip install pyinstaller

# builder (script automatique)
.\build_exe.ps1 -Name "cbz_to_epub" -OneFile
```

L'exécutable (ou le dossier) apparaîtra dans `dist/`.

Remarques importantes :
- `ebook-convert` (Calibre) n'est pas inclus : il doit être installé séparément sur la machine cible et accessible dans le PATH.
- Selon la version de PyQt6 et PyInstaller, il peut être nécessaire d'ajouter `--hidden-import` ou d'ajuster `--add-data` pour inclure des plugins Qt (ex. plateformes). En cas de problèmes, consulte la sortie de PyInstaller et adapte la commande.

Si tu veux, je peux aussi :
- créer automatiquement un `requirements.txt` (ex : `PyQt6`) et un `LICENSE` MIT,
- ajouter un template GitHub Actions qui exécute `python -m py_compile` sur les fichiers Python pour CI,
- préparer un commit initial (`README.md`, `.gitignore`, `LICENSE`).

