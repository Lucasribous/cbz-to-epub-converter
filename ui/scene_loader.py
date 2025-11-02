"""scene_loader.py — Loads all Figma JSON scenes into PyQt widgets."""

from pathlib import Path
from typing import List
from ui.base_scene import BaseScene


def load_scenes(parent) -> List[BaseScene]:
    """Load all JSON scenes from the local `scene/` directory and add them to the parent QStackedWidget.

    Returns the list of created BaseScene widgets (in sorted filename order).
    """
    # folder in the repo is `scene/` (not `scenes/`)
    scene_dir = Path(__file__).parent.parent / "scene"
    if not scene_dir.exists():
        print(f"Warning: scene directory not found: {scene_dir}")
        return []

    scene_paths = sorted(scene_dir.glob("*.json"))
    scenes: List[BaseScene] = []
    for path in scene_paths:
            # Pre-validate the JSON file: some files (like images.json) are lists, not scenes
            try:
                import json
                with open(path, "r", encoding="utf-8") as fh:
                    parsed = json.load(fh)
            except Exception as e:
                print(f"Skipping {path.name}: cannot parse JSON ({e})")
                continue

            # We expect scene JSONs to be objects (dict). Skip lists or other types.
            if not isinstance(parsed, dict):
                print(f"Skipping {path.name}: not a scene JSON (type={type(parsed).__name__})")
                continue

            print(f"Loading scene: {path.name}")
            scene = BaseScene(str(path), parent)
            # parent is expected to be a QStackedWidget
            try:
                parent.addWidget(scene)
            except Exception:
                # fallback: ignore if parent is not a stacked widget
                pass
            scenes.append(scene)

    return scenes
