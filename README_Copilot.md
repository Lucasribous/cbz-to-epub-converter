🧠 CBZ → EPUB Converter — UI Phase Only

Language: Python 3.13
Framework: PyQt6
Goal: Build a full desktop application that converts .cbz manga archives into .epub ebooks.
Current phase: Build and test the UI and scene transitions only (no logic yet).

-----------------------------------------------------------------------------------------------------------------------------------------

🎯 Project Description

The app allows users to:

Select an input folder containing .cbz manga files

Select an output folder for .epub files

Enter author and series name

Watch progress bars and LED indicators during conversion

Generate a log (log.txt) summarizing success/failure

👉 For now, this phase only aims to display and navigate between all 9 scenes from the provided Figma JSONs.

-----------------------------------------------------------------------------------------------------------------------------------------

🧩 Scenes Overview

| ID | File                       | Description                        |
| -- | -------------------------- | ---------------------------------- |
| 01 | `01_Home.json`             | Default screen at launch           |
| 02 | `02_cbz_ok.json`           | After selecting CBZ input folder   |
| 03 | `02_epub_ok.json`          | After selecting EPUB output folder |
| 04 | `03_cbz_epub_ok.json`      | When both folders are selected     |
| 05 | `04_metadata.json`         | Step for entering metadata         |
| 06 | `05_author.json`           | Step for entering author name      |
| 07 | `06_serie.json`            | Step for entering series name      |
| 08 | `07_start_conversion.json` | Step before starting conversion    |
| 09 | `08_working.json`          | While conversion is in progress    |
| 10 | `09_end.json`              | After conversion is finished       |

✅ For now:

All scenes are static and loaded from JSON

Clicking the “Next” button just switches to the next scene

No conversion or file logic yet

A fade transition (300–400 ms) between scenes is required

-----------------------------------------------------------------------------------------------------------------------------------------

🧱 Folder Structure

/project_root
│
├── main.py
│
├── ui/
│   ├── base_scene.py
│   ├── scene_loader.py
│   ├── components.py
│
├── scenes/
│   ├── 01_Home.json
│   ├── 02_cbz_ok.json
│   ├── 02_epub_ok.json
│   ├── 03_cbz_epub_ok.json
│   ├── 04_metadata.json
│   ├── 05_author.json
│   ├── 06_serie.json
│   ├── 07_start_conversion.json
│   ├── 08_working.json
│   └── 09_end.json
│
├── assets/
│   ├── images/
│   ├── fonts/
│   ├── icons/
│
└── README_Copilot.md

-----------------------------------------------------------------------------------------------------------------------------------------

🧩 Development Rules

Each .json in /scenes/ defines one scene exported from Figma

The UI must be dynamically built from these JSON files (no hardcoded widgets)

The main window uses QStackedWidget to switch between scenes

Scene transitions must use a fade effect (QGraphicsOpacityEffect)

Window size: 1290×818 px, not resizable

The “Next” button (bottom right) allows manual navigation

No conversion logic, metadata handling, or file I/O at this stage

-----------------------------------------------------------------------------------------------------------------------------------------

🧱 Base Files to Create

main.py

Launches the PyQt6 app

Loads all scenes from /scenes/ via scene_loader.py

Handles “Next” button navigation

Fixed size (1290×818) and fade transitions

ui/base_scene.py

Reads a Figma JSON

Dynamically creates QLabel, QPushButton, etc.

Positions them using absoluteBoundingBox data

Applies background images, fonts, and text

ui/scene_loader.py

Loads all JSON files in /scenes/

Creates one BaseScene per file

Adds each scene to QStackedWidget

ui/components.py

Contains helper functions:

fade_transition() for smooth transitions

-----------------------------------------------------------------------------------------------------------------------------------------

🧠 Behavior Summary

App launches → displays 01_Home

Clicking “Next” or pressing Enter → shows the next scene

Last scene loops back to 01_Home

Fade animation between transitions

All images and layout positions come from the JSON data

-----------------------------------------------------------------------------------------------------------------------------------------

🚫 Do NOT Implement Yet

Folder selection logic

CBZ/EPUB conversion or repair

Metadata entry or validation

Log generation

Threads or background workers

This phase is for UI visualization only.

-----------------------------------------------------------------------------------------------------------------------------------------

🧩 Future Phases (not for now)

Functional logic — connect buttons to real actions

Conversion system — repair CBZ, convert to EPUB

Log generation — automatic log.txt after conversion

CRT visual mode — retro shader filter

Automatic batch mode — one-click processing

-----------------------------------------------------------------------------------------------------------------------------------------

✅ Task for Copilot

Task:
Read this file, create the UI skeleton for all 9 scenes, and make them switch with a fade transition.

Use the provided ui/base_scene.py, ui/scene_loader.py, and ui/components.py structure.

Each scene must be generated dynamically from its JSON in /scenes/.

Do not implement logic or backend yet — this is for UI testing only.

-----------------------------------------------------------------------------------------------------------------------------------------

💡 Commands to Use in Copilot Chat

After opening this file and the /scenes/ folder:
@copilot Read README_Copilot.md and generate the PyQt6 app UI according to this structure.

Then, when code is generated:
python main.py

-----------------------------------------------------------------------------------------------------------------------------------------

🧩 Copilot Checklist

✅ Step 1:
Create the following files if they don’t exist:

main.py

ui/base_scene.py

ui/scene_loader.py

ui/components.py

✅ Step 2:
In main.py:

Create the MainApp(QStackedWidget) class

Load all scenes from /scenes/

Add a “Next” button to switch between scenes

Implement fade transitions using components.py

✅ Step 3:
In ui/base_scene.py:

Parse JSON layout data (absoluteBoundingBox, widgetType, etc.)

Create corresponding PyQt widgets dynamically

Apply fonts and background if defined

✅ Step 4:
In ui/scene_loader.py:

Iterate over all JSON files in /scenes/

Instantiate BaseScene for each

Add them to the main QStackedWidget

✅ Step 5:
In ui/components.py:

Implement fade_transition() with QGraphicsOpacityEffect

Ensure smooth fade-in/out (duration ~400 ms)

✅ Step 6:
Test the app by running:
python main.py

You should see the first scene load, and clicking “Next” should smoothly transition through all 9 scenes.

✅ Step 7:
Once UI navigation works, stop here.
Do not add conversion logic yet — next phase will implement functional features.
-----------------------------------------------------------------------------------------------------------------------------------------

🧩 Coding Style Guidelines

Python 3.13

Use typed functions (def func(x: str) -> bool:)

Use English comments and docstrings

Keep code modular and simple

Each file serves one purpose only

Compatible with Windows (PyInstaller ready)

-----------------------------------------------------------------------------------------------------------------------------------------

✅ Once this phase is validated, we’ll proceed to functional logic integration (conversion, logs, etc.)