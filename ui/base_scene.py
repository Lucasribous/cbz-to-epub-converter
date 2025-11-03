"""base_scene.py — Minimal Figma JSON -> QWidget renderer for UI preview.

This parser is intentionally lightweight: it supports text nodes and image fills exported
by the Figma JSONs in the repository. It places widgets using the node's x/y/width/height
properties that appear in the provided JSON exports.
"""

import json
import os
import logging
import subprocess
import platform
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QWidget, QLabel, QPushButton, QFileDialog, QMessageBox, QLineEdit
from PyQt6.QtGui import QPixmap, QFont, QIcon, QFontDatabase, QPainter, QColor
from PyQt6.QtCore import Qt, QSize, QTimer


# Register application fonts from assets/fonts so we can use them by name.
LOADED_FONT_FAMILIES: list[str] = []
def _register_fonts_once() -> None:
    global LOADED_FONT_FAMILIES
    if LOADED_FONT_FAMILIES:
        return
    fonts_dir = Path(__file__).parent.parent / "assets" / "fonts"
    if not fonts_dir.exists():
        return
    for fp in fonts_dir.iterdir():
        if fp.suffix.lower() in (".ttf", ".otf"):
            try:
                fid = QFontDatabase.addApplicationFont(str(fp))
                if fid != -1:
                    families = QFontDatabase.applicationFontFamilies(fid)
                    for fam in families:
                        LOADED_FONT_FAMILIES.append(fam)
            except Exception:
                pass

# Register fonts now (module import)
# Note: do not register fonts at module import time — this can crash on some
# platforms if Qt's application object is not yet created. Registration is
# performed lazily in BaseScene.__init__ where a QApplication is already
# expected to exist.


class HoverButton(QPushButton):
    """QPushButton that swaps icon on hover when hover icon is provided."""
    def __init__(self, parent=None, normal_icon: QIcon | None = None, hover_icon: QIcon | None = None, icon_size: QSize | None = None):
        super().__init__(parent)
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        if self._normal_icon:
            self.setIcon(self._normal_icon)
        if icon_size:
            self.setIconSize(icon_size)

    def enterEvent(self, event):
        if self._hover_icon:
            self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._normal_icon:
            self.setIcon(self._normal_icon)
        super().leaveEvent(event)


class SquareHoverButton(QPushButton):
    """Button that shows a colored rectangle on hover (normal cursor).

    Accepts explicit width and height so small rectangular controls (14px high)
    can be used. Hover shows a semi-transparent rectangle using `hover_color`.
    """
    def __init__(self, parent=None, hover_color: str = '#000000', width: int = 14, height: int = 14):
        super().__init__(parent)
        self.hover_color = hover_color
        self._w = int(width)
        self._h = int(height)
        self.setFixedSize(self._w, self._h)
        self.setFlat(True)
        # start transparent
        self.setStyleSheet('background: transparent; border: none;')
        try:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            pass

    def enterEvent(self, event):
        try:
            # show a semi-transparent rectangle of the hover color at 50% opacity
            col = self.hover_color.lstrip('#')
            if len(col) == 6:
                r = int(col[0:2], 16)
                g = int(col[2:4], 16)
                b = int(col[4:6], 16)
                self.setStyleSheet(f'background: rgba({r}, {g}, {b}, 0.5); border: none;')
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        try:
            self.setStyleSheet('background: transparent; border: none;')
        except Exception:
            pass
        super().leaveEvent(event)


class DragArea(QWidget):
    """Transparent widget that lets the user drag the top-level window.

    Designed to be placed at x=1008,y=0 size 282x14 in the scene. It accepts
    mouse events and moves the window accordingly. The visual appearance is
    fully transparent (stylesheet) so the scene artwork remains visible.
    """
    def __init__(self, parent=None, width:int=282, height:int=14):
        super().__init__(parent)
        self._pressed = False
        self._offset = None
        self.setFixedSize(width, height)
        # transparent but accepts mouse events
        self.setStyleSheet('background: transparent;')
        try:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            pass

    def mousePressEvent(self, event):
        try:
            if event.button() == Qt.MouseButton.LeftButton:
                gp = event.globalPosition()
                try:
                    pt = gp.toPoint()
                except Exception:
                    pt = gp
                w = self.window()
                if w is None:
                    return
                try:
                    self._offset = pt - w.frameGeometry().topLeft()
                    self._pressed = True
                except Exception:
                    self._offset = None
        except Exception:
            pass

    def mouseMoveEvent(self, event):
        try:
            if not self._pressed or self._offset is None:
                return
            gp = event.globalPosition()
            try:
                pt = gp.toPoint()
            except Exception:
                pt = gp
            new_tl = pt - self._offset
            try:
                self.window().move(new_tl)
            except Exception:
                pass
        except Exception:
            pass

    def mouseReleaseEvent(self, event):
        try:
            self._pressed = False
            self._offset = None
        except Exception:
            pass


class BaseScene(QWidget):
    """Builds a QWidget from a Figma JSON export.

    It creates QLabel widgets for images (fills of type IMAGE) and for text nodes
    (nodes with type 'TEXT' or a 'characters' field). Positioning uses the node's
    x/y/width/height fields (as present in the provided JSON files).
    """

    def __init__(self, json_path: str, parent=None):
        super().__init__(parent)
        # Ensure fonts are registered after a QApplication exists.
        try:
            _register_fonts_once()
        except Exception:
            # Avoid raising here; font registration is optional.
            pass
        self.json_path = json_path
        self.assets_dir = Path(__file__).parent.parent / "assets" / "images"
        # Enable debug visuals/logs while we diagnose positioning and routing.
        # Set debug from environment variable DEBUG_UI=1, default False.
        self.DEBUG = os.environ.get("DEBUG_UI", "0") == "1"
        # Collected text zones for this scene (name, text, rect, widget)
        self.text_zones = []
        # preserved initial text metadata so typing can restart when scene shown again
        self._initial_texts: list[dict] = []  # items: {'lbl': QLabel, 'full': str, 'animate_ellipsis': bool}
        # Typing animation: labels to animate (list of dicts: {lbl, full, pos})
        self._typing_labels = []
        self._typing_timer = QTimer(self)
        # default typing speed (ms per character)
        self._typing_timer.setInterval(25)
        self._typing_timer.timeout.connect(self._update_typing)
        # Ellipsis animation state: labels that should cycle '.', '..', '...'
        self._ellipsis_labels = []  # items: {'lbl': QLabel, 'prefix': str, 'state': int}
        self._ellipsis_timer = QTimer(self)
        self._ellipsis_timer.setInterval(500)
        self._ellipsis_timer.timeout.connect(self._update_ellipses)
        # progress widgets for working scene (keys: 'repaired', 'converted')
        self._progress_widgets = {}
        # per-key animation state: { key: { 'current': float, 'timer': QTimer | None, 'steps_left': int, 'step_delta': float } }
        self._progress_states = {}
        # conversion running flag
        self._conversion_running = False
        self._load()

    def showEvent(self, event):
        # Before starting typing, allow scene-specific runtime substitutions
        try:
            cur_base = os.path.basename(str(self.json_path or ""))
            par = self.parent()
            # For the final scene, replace placeholders with runtime values
            if cur_base == '09_end.json' and par is not None:
                try:
                    count = len(getattr(par, 'selected_cbz_files', []) or [])
                except Exception:
                    count = 0
                try:
                    out = str(getattr(par, 'selected_epub_output_dir', '') or '')
                    # shorten to last two path segments, prefixed with '/'
                    if out:
                        try:
                            parts = list(Path(out).parts)
                            if len(parts) >= 2:
                                short = '/' + '/'.join(parts[-2:])
                            else:
                                short = '/' + parts[-1] if parts else ''
                            out = short
                        except Exception:
                            # fallback to raw string
                            out = str(out)
                except Exception:
                    out = ''
                # update any initial_texts that contain the placeholders
                for meta in self._initial_texts:
                    try:
                        full = meta.get('full', '') or ''
                        if '{n}' in full or '{output path}' in full:
                            new_full = full.replace('{n}', str(count)).replace('{output path}', out)
                            meta['full'] = new_full
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            self._start_typing()
        except Exception:
            pass
        # If this is the working scene, request the parent to start conversion
        try:
            cur_base = os.path.basename(str(self.json_path or ""))
            if cur_base == '08_working.json':
                par = self.parent()
                if par is not None and hasattr(par, 'start_conversion'):
                    try:
                        par.start_conversion()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            super().showEvent(event)
        except Exception:
            pass

    def hideEvent(self, event):
        try:
            self._stop_typing()
        except Exception:
            pass
        try:
            super().hideEvent(event)
        except Exception:
            pass

    def _update_typing(self) -> None:
        """Advance typing for all tracked labels by one character per tick."""
        if not self._typing_labels:
            try:
                if self._typing_timer.isActive():
                    self._typing_timer.stop()
            except Exception:
                pass
            return

        for item in list(self._typing_labels):
            try:
                lbl = item.get('lbl')
                full = item.get('full', '')
                pos = item.get('pos', 0)
                if pos < len(full):
                    pos += 1
                    item['pos'] = pos
                    try:
                        lbl.setText(full[:pos])
                    except Exception:
                        pass
                else:
                    # finished typing for this label
                    try:
                        full_str = (full or '')
                        tail = full_str.rstrip()
                        # detect both three-dot and unicode ellipsis
                        if tail.endswith('...') or tail.endswith('…'):
                            # compute base without the trailing ellipsis
                            if tail.endswith('...'):
                                base = tail[:-3]
                            else:
                                base = tail[:-1]
                            try:
                                lbl.setText(base + '.')
                            except Exception:
                                pass
                            # start ellipsis animation for this label
                            self._ellipsis_labels.append({'lbl': lbl, 'prefix': base, 'state': 1})
                            try:
                                if not self._ellipsis_timer.isActive():
                                    self._ellipsis_timer.start()
                            except Exception:
                                pass
                        try:
                            self._typing_labels.remove(item)
                        except ValueError:
                            pass
                    except Exception:
                        # swallow errors per previous pattern
                        try:
                            self._typing_labels.remove(item)
                        except Exception:
                            pass
            except Exception:
                pass

    def _start_typing(self) -> None:
        """Reset positions and start the typing timer for this scene."""
        # Rebuild typing list from preserved initial metadata so typing
        # restarts when the scene is shown again (e.g. after Reset).
        try:
            # reset any previous ellipsis state
            self._ellipsis_labels = []
            if self._ellipsis_timer.isActive():
                self._ellipsis_timer.stop()
        except Exception:
            pass

        # prepare typing items from initial metadata
        self._typing_labels = []
        for meta in self._initial_texts:
            try:
                lbl = meta.get('lbl')
                full = meta.get('full', '') or ''
                animate = bool(meta.get('animate_ellipsis'))
                try:
                    lbl.setText("")
                except Exception:
                    pass
                self._typing_labels.append({'lbl': lbl, 'full': full, 'pos': 0, 'animate_ellipsis': animate})
            except Exception:
                pass

        try:
            if self._typing_labels and not self._typing_timer.isActive():
                self._typing_timer.start()
        except Exception:
            pass

    def _stop_typing(self) -> None:
        try:
            if self._typing_timer.isActive():
                self._typing_timer.stop()
        except Exception:
            pass
        try:
            if self._ellipsis_timer.isActive():
                self._ellipsis_timer.stop()
        except Exception:
            pass

    def _load(self) -> None:
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"Failed to load scene {self.json_path}: {e}")
            return

        # Set scene size if provided (frame width/height)
        width = data.get("width", 1290)
        height = data.get("height", 818)
        self.setFixedSize(int(width), int(height))

        # Recursively parse children. The top-level frame in Figma may have
        # an origin (x,y) not equal to (0,0) in the document; normalize by
        # passing an offset that shifts the document so the frame's origin
        # becomes (0,0) inside our widget coordinate space.
        root_x = int(data.get("x", 0))
        root_y = int(data.get("y", 0))
        self._parse_node(data, -root_x, -root_y)

        # Global window control buttons (minimize / close) positioned on every scene
        try:
            # Minimize button at x=1236,y=0 (20x14) with hover rectangle (#4e55c7 @50%)
            try:
                btn_min = SquareHoverButton(self, hover_color='#4e55c7', width=20, height=14)
                btn_min.setGeometry(1236, 0, 20, 14)
                try:
                    btn_min.clicked.connect(lambda _checked=False, s=self: s.window().showMinimized())
                except Exception:
                    pass
                try:
                    btn_min.raise_()
                except Exception:
                    pass
            except Exception:
                pass

            # Close button at x=1261,y=0 (20x14) with hover rectangle (#fb0000 @50%)
            try:
                btn_close = SquareHoverButton(self, hover_color='#fb0000', width=20, height=14)
                btn_close.setGeometry(1261, 0, 20, 14)
                try:
                    btn_close.clicked.connect(lambda _checked=False, s=self: s.window().close())
                except Exception:
                    pass
                try:
                    btn_close.raise_()
                except Exception:
                    pass
            except Exception:
                pass

            # Transparent drag area below the close/minimize buttons: acts as title bar
            # NOTE: width reduced so it does not overlap the minimize/close buttons.
            try:
                drag = DragArea(self, width=223, height=14)
                drag.setGeometry(1008, 0, 223, 14)
                try:
                    # ensure the drag area stays behind the control buttons
                    drag.lower()
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def _parse_node(self, node: Any, offset_x: int = 0, offset_y: int = 0) -> None:
        # Node may be dict or list
        if isinstance(node, dict):
            # If node has fills with IMAGE, create QLabel with the image
            fills = node.get("fills", [])
            img_src = None
            for f in fills:
                if isinstance(f, dict) and f.get("type") == "IMAGE":
                    # 'src' may be like 'images/<filename>'
                    img_src = f.get("src")
                    break

            # Prefer absoluteBoundingBox if present (Figma exports often include it).
            # absoluteBoundingBox uses absolute coordinates; otherwise use node x/y
            # plus the accumulated offset from parent instances.
            ab = node.get("absoluteBoundingBox") or {}
            if isinstance(ab, dict) and ab.get("x") is not None:
                x = int(ab.get("x", 0))
                y = int(ab.get("y", 0))
            else:
                x = int(node.get("x", 0)) + int(offset_x)
                y = int(node.get("y", 0)) + int(offset_y)

            # width/height: if absoluteBoundingBox provided, prefer those values
            if isinstance(ab, dict) and ab.get("width") is not None:
                w = int(ab.get("width", 0))
                h = int(ab.get("height", 0))
            else:
                w = int(node.get("width", 0))
                h = int(node.get("height", 0))

            # For children recursion we need the position of this node as an offset
            # so child nodes with x=0,y=0 inside this node are placed correctly.
            cur_offset_x = x
            cur_offset_y = y

            if img_src:
                # extract filename from src
                fname = os.path.basename(img_src)
                candidate = self.assets_dir / fname
                lbl = QLabel(self)
                if candidate.exists():
                    pix = QPixmap(str(candidate))
                    if pix.isNull():
                        # Failed to load image data; fallback to text placeholder
                        if self.DEBUG:
                            print(f"[WARN] QPixmap failed to load {candidate}")
                        lbl.setText(fname)
                        lbl.setGeometry(x, y, max(10, w or 100), max(10, h or 20))
                        pix = None
                    
                    # If the JSON provides width/height we MUST place the image
                    # exactly at (x,y) with that size to achieve pixel-perfect layout.
                    # Use IgnoreAspectRatio so the pixmap fills the rectangle exactly.
                    if pix is not None:
                        if w and h:
                            pix = pix.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                            lbl.setPixmap(pix)
                            lbl.setGeometry(x, y, int(w), int(h))
                            lbl.setScaledContents(True)
                            # register progress widgets if these are the bar images
                            try:
                                if fname in ("repaired_files_progress_bar.png", "converted_files_progress_bar.png"):
                                    key = 'repaired' if 'repaired' in fname else 'converted'
                                    # store the pixmap as the original full-size for cropping
                                    # create a colored overlay widget on top of the label
                                    try:
                                        logger = logging.getLogger('cbz_ui')
                                        logger.debug(f"[PROG_UI] registered progress widget key={key} fname={fname} geom=({x},{y},{w},{h}) pix={pix.width()}x{pix.height()}")
                                        if self.DEBUG:
                                            print(f"[PROG_UI] registered key={key} fname={fname} geom=({x},{y},{w},{h}) pix={pix.width()}x{pix.height()}")
                                    except Exception:
                                        pass

                                    # schedule an initial empty progress render
                                    try:
                                        QTimer.singleShot(0, lambda k=key: self.set_progress_bar(k, 0.0))
                                    except Exception:
                                        pass

                                    # store only the minimal data needed for rendering
                                    self._progress_widgets[key] = {'lbl': lbl, 'orig_pix': pix}
                            except Exception:
                                pass
                        else:
                            lbl.setPixmap(pix)
                            lbl.setGeometry(x, y, pix.width(), pix.height())
                else:
                    # fallback: display the src text so missing assets are visible
                    lbl.setText(fname)
                    lbl.setGeometry(x, y, max(10, w or 100), max(10, h or 20))
                lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                # If this image represents an interactive button we create an
                # invisible QPushButton exactly on top of the image to receive clicks.
                interactive_buttons = {
                    "cbz_button.png": "02_cbz_ok.json",
                    "epub_button.png": "02_epub_ok.json",
                    "conversion_button.png": "08_working.json",
                    "log_button.png": None,
                    "next_button.png": "__NEXT__",
                    "reset_button.png": "01_Home.json",
                }

                if fname in interactive_buttons:
                    # prepare icons for normal and hover states if available
                    # compute current scene base name early so we can skip
                    # the next_button on the working scene (automatic transition)
                    cur_name = os.path.basename(str(self.json_path or ""))
                    if cur_name == '08_working.json' and fname == 'next_button.png':
                        # intentionally do not create an interactive Next button
                        # on the working scene because transitions are automatic.
                        skip_button = True
                    else:
                        skip_button = False
                    normal_icon = None
                    hover_icon = None
                    icon_size = None
                    if candidate.exists() and pix is not None:
                        normal_icon = QIcon(pix)
                        icon_size = QSize(int(w or pix.width()), int(h or pix.height()))
                        # look for hover variant like name_hover.png
                        hover_name = fname.replace('.png', '_hover.png')
                        hover_path = self.assets_dir / hover_name
                        if hover_path.exists():
                            hover_pix = QPixmap(str(hover_path))
                            if hover_pix.isNull():
                                if self.DEBUG:
                                    print(f"[WARN] hover QPixmap failed to load {hover_path}")
                                hover_pix = None
                            if hover_pix is not None:
                                if w and h:
                                    hover_pix = hover_pix.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                                hover_icon = QIcon(hover_pix)

                    # Determine whether this button should be enabled for navigation.
                    parent = self.parent()
                    cur_name = os.path.basename(str(self.json_path or ""))
                    # Disable hover visuals for buttons that should not show hover
                    # (log button is only active on 09_end, conversion only on 07_start_conversion)
                    try:
                        if (fname == 'log_button.png' and cur_name != '09_end.json') or (
                            fname == 'conversion_button.png' and cur_name != '07_start_conversion.json'
                        ):
                            hover_icon = None
                    except Exception:
                        pass
                    # resolve base mapping
                    target_rt = interactive_buttons.get(fname)
                    # apply same special-case routing as at click time so the
                    # button enabled state matches runtime resolution
                    if cur_name == "02_cbz_ok.json" and fname == "epub_button.png":
                        target_rt = "03_cbz_epub_ok.json"
                    if cur_name == "02_epub_ok.json" and fname == "cbz_button.png":
                        target_rt = "03_cbz_epub_ok.json"
                    try:
                        allowed = parent.is_navigation_allowed(cur_name, target_rt, fname) if parent is not None and hasattr(parent, 'is_navigation_allowed') else True
                    except Exception:
                        allowed = True

                    # Do not remove hover icons based on allowed state here;
                    # we'll reflect allowed/not-allowed via the cursor and
                    # optionally refresh buttons later when metadata changes.

                    if not skip_button:
                        btn = HoverButton(self, normal_icon=normal_icon, hover_icon=hover_icon, icon_size=icon_size)
                    else:
                        btn = None

                    if btn is not None:
                        btn.setFlat(True)
                        # remember which asset this button represents so we
                        # can refresh its cursor/availability later
                        try:
                            setattr(btn, '_asset_name', fname)
                        except Exception:
                            pass
                        # Do not visually disable the button; use cursor to indicate
                        # availability. Cursor will be set below.
                        btn.setStyleSheet("background: transparent; border: none;")
                        # place button exactly where the image is
                        btn.setGeometry(x, y, int(w or lbl.width()), int(h or lbl.height()))

                        # Keep button enabled; change cursor to forbidden if not allowed
                        btn.setEnabled(True)
                        try:
                            # Conversion button: only available (clickable) when
                            # the user is on scene 07_start_conversion. Otherwise
                            # indicate unavailability via the Forbidden cursor
                            if fname == 'conversion_button.png':
                                try:
                                    if cur_name == '07_start_conversion.json':
                                        btn.setCursor(Qt.CursorShape.PointingHandCursor)
                                    else:
                                        btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                                except Exception:
                                    btn.setCursor(Qt.CursorShape.ArrowCursor)
                            # Log button: clickable only on final scene
                            elif fname == 'log_button.png':
                                try:
                                    if cur_name == '09_end.json':
                                        btn.setCursor(Qt.CursorShape.PointingHandCursor)
                                    else:
                                        btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                                except Exception:
                                    btn.setCursor(Qt.CursorShape.ArrowCursor)
                            else:
                                try:
                                    if not allowed:
                                        btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                                    else:
                                        btn.setCursor(Qt.CursorShape.PointingHandCursor)
                                except Exception:
                                    btn.setCursor(Qt.CursorShape.ArrowCursor)
                        except Exception:
                            btn.setCursor(Qt.CursorShape.ArrowCursor)
                    else:
                        # In some scenes we intentionally skip creating the
                        # interactive overlay (e.g. next button on working scene).
                        if self.DEBUG:
                            print(f"[DBG] skipped creating interactive button for {fname} on {os.path.basename(str(self.json_path))}")

                    # connect click to navigation handler (if mapping specifies a target scene)
                    # Support special actions and scene-specific branch logic:
                    # Instead of capturing a possibly stale 'target' value at
                    # definition time, resolve the target at click time. This
                    # avoids closure/ordering issues and handles special-case
                    # routing (02_* -> 03).
                    def _on_click_runtime():
                        parent = self.parent()
                        cur_name = os.path.basename(str(self.json_path or ""))
                        # resolve base mapping
                        target_rt = interactive_buttons.get(fname)

                        # apply special-case routing
                        if cur_name == "02_cbz_ok.json" and fname == "epub_button.png":
                            target_rt = "03_cbz_epub_ok.json"
                        if cur_name == "02_epub_ok.json" and fname == "cbz_button.png":
                            target_rt = "03_cbz_epub_ok.json"

                        # debug log for click resolution
                        try:
                            logging.getLogger("cbz_ui").debug(f"[CLICK_RUNTIME] scene={cur_name} fname={fname} -> target_rt={target_rt}")
                        except Exception:
                            pass
                        if self.DEBUG:
                            print(f"[CLICK_RUNTIME] scene={cur_name} fname={fname} -> target_rt={target_rt}")

                        # Immediate action: if this is the log button, handle it
                        # before navigation checks so it works even when target_rt is None.
                        if fname == "log_button.png":
                            # Generate the session log and open the output folder with the file selected
                            try:
                                par = self.parent()
                                if par is None:
                                    return
                                # Only allow log action on final scene
                                if cur_name != '09_end.json':
                                    if self.DEBUG:
                                        print(f"[LOG_BLOCKED] log button clicked on {cur_name}")
                                    return
                                if not hasattr(par, 'generate_log'):
                                    try:
                                        QMessageBox.warning(self, 'Erreur', 'Générateur de log indisponible')
                                    except Exception:
                                        pass
                                    return
                                path = None
                                try:
                                    path = par.generate_log()
                                except Exception as e:
                                    try:
                                        QMessageBox.warning(self, 'Échec', f"Impossible de générer le log : {e}")
                                    except Exception:
                                        pass
                                    try:
                                        logging.getLogger('cbz_ui').exception('Log generation failed')
                                    except Exception:
                                        pass
                                    return

                                if not path:
                                    try:
                                        QMessageBox.information(self, 'Log', 'Le fichier log n\'a pas pu être généré.')
                                    except Exception:
                                        pass
                                    return

                                # Try to open the containing folder and select the log file (Windows)
                                try:
                                    p = Path(path)
                                    if os.name == 'nt' or platform.system() == 'Windows':
                                        # explorer /select,<path>
                                        subprocess.run(['explorer', '/select,', str(p)], check=False)
                                    else:
                                        # Fallback: open the folder containing the log file
                                        folder = str(p.parent)
                                        if platform.system() == 'Darwin':
                                            subprocess.run(['open', folder], check=False)
                                        else:
                                            subprocess.run(['xdg-open', folder], check=False)
                                except Exception:
                                    # If opening the folder fails, show the path to the user
                                    try:
                                        QMessageBox.information(self, 'Log généré', f'Le fichier log a été enregistré:\n{path}')
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            return

                        # Check allowed at click-time also
                        try:
                            if parent is not None and hasattr(parent, 'is_navigation_allowed'):
                                allowed = parent.is_navigation_allowed(cur_name, target_rt, fname)
                                try:
                                    logging.getLogger("cbz_ui").debug(f"[NAV_CHECK] {cur_name} -> {target_rt} via {fname} allowed={allowed}")
                                except Exception:
                                    pass
                                if not allowed:
                                    if self.DEBUG:
                                        print(f"[NAV_BLOCKED] {cur_name} -> {target_rt} via {fname}")
                                    return
                        except Exception:
                            pass

                        # handle next action
                        if target_rt == "__NEXT__":
                            if parent is None:
                                return
                            if hasattr(parent, "next_scene"):
                                try:
                                    logging.getLogger("cbz_ui").debug(f"[NAV_ACTION] next requested from {cur_name}")
                                except Exception:
                                    pass
                                try:
                                    parent.next_scene()
                                except Exception:
                                    pass
                            return

                        # Special-case: if this is the CBZ chooser button, open a file dialog
                        if fname == "cbz_button.png":
                            try:
                                # allow multiple selection of .cbz files only
                                files, _ = QFileDialog.getOpenFileNames(self, "Select CBZ files to convert", "", "CBZ files (*.cbz)")
                                if not files:
                                    # user cancelled — do not navigate
                                    try:
                                        logging.getLogger("cbz_ui").debug("[CBZ] user cancelled selection")
                                    except Exception:
                                        pass
                                    return

                                # store selection on parent if possible
                                if parent is not None:
                                    try:
                                        if hasattr(parent, 'set_cbz_files'):
                                            parent.set_cbz_files(files)
                                        else:
                                            setattr(parent, 'selected_cbz_files', files)
                                        try:
                                            logging.getLogger("cbz_ui").info(f"[CBZ] selected {len(files)} file(s)")
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                # mark CBZ as selected on the parent so UI can refresh
                                try:
                                    if parent is not None:
                                        try:
                                            setattr(parent, '_cbz_selected', True)
                                        except Exception:
                                            pass
                                        # refresh interactive buttons on all loaded scenes
                                        try:
                                            for i in range(parent.count()):
                                                w = parent.widget(i)
                                                if hasattr(w, 'refresh_interactive_buttons'):
                                                    try:
                                                        w.refresh_interactive_buttons()
                                                    except Exception:
                                                        pass
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            except Exception as e:
                                # show an error to the user minimally
                                try:
                                    QMessageBox.warning(self, "File selection failed", f"Could not open file chooser: {e}")
                                except Exception:
                                    pass
                                try:
                                    logging.getLogger("cbz_ui").exception("CBZ file dialog failed")
                                except Exception:
                                    pass
                                return

                        # Special-case: if this is the EPUB output folder chooser
                        if fname == "epub_button.png":
                            try:
                                # Choose an existing directory for EPUB output
                                folder = QFileDialog.getExistingDirectory(self, "Select output folder for EPUB files", "")
                                if not folder:
                                    # user cancelled — do not navigate
                                    try:
                                        logging.getLogger("cbz_ui").debug("[EPUB] user cancelled selection")
                                    except Exception:
                                        pass
                                    return

                                # store selection on parent if possible
                                if parent is not None:
                                    try:
                                        if hasattr(parent, 'set_epub_output_dir'):
                                            parent.set_epub_output_dir(folder)
                                        else:
                                            setattr(parent, 'selected_epub_output_dir', folder)
                                        try:
                                            logging.getLogger("cbz_ui").info(f"[EPUB] selected output folder: {folder}")
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                # mark EPUB as selected on the parent so UI can refresh
                                try:
                                    if parent is not None:
                                        try:
                                            setattr(parent, '_epub_selected', True)
                                        except Exception:
                                            pass
                                        try:
                                            for i in range(parent.count()):
                                                w = parent.widget(i)
                                                if hasattr(w, 'refresh_interactive_buttons'):
                                                    try:
                                                        w.refresh_interactive_buttons()
                                                    except Exception:
                                                        pass
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                            except Exception as e:
                                try:
                                    QMessageBox.warning(self, "Folder selection failed", f"Could not open folder chooser: {e}")
                                except Exception:
                                    pass
                                try:
                                    logging.getLogger("cbz_ui").exception("EPUB folder dialog failed")
                                except Exception:
                                    pass
                                return

                        

                        # no explicit target
                        if not target_rt:
                            try:
                                logging.getLogger("cbz_ui").warning(f"Target scene not found: {target_rt}")
                            except Exception:
                                pass
                            print(f"Target scene not found: {target_rt}")
                            return

                        # find loaded scene with matching json_path
                        if parent is None:
                            return
                        for i in range(parent.count()):
                            w = parent.widget(i)
                            jp = getattr(w, "json_path", None)
                            if not isinstance(jp, str):
                                continue
                            if isinstance(target_rt, str) and jp.endswith(target_rt):
                                # clear any leftover opacity effect (widgets may have
                                # been faded out previously) so the scene is visible
                                try:
                                    w.setGraphicsEffect(None)
                                except Exception:
                                    pass
                                try:
                                    logging.getLogger("cbz_ui").debug(f"[NAV] switching to {jp}")
                                except Exception:
                                    pass
                                if self.DEBUG:
                                    print(f"[NAV] switching to {jp}")
                                parent.setCurrentIndex(i)
                                return
                        try:
                            logging.getLogger("cbz_ui").warning(f"Target scene not found: {target_rt}")
                        except Exception:
                            pass
                        print(f"Target scene not found: {target_rt}")

                    # connect only if we actually created a button (skip_button may be True)
                    if btn is not None:
                        try:
                            btn.clicked.connect(_on_click_runtime)
                        except Exception:
                            # log but don't crash scene parsing
                            try:
                                logging.getLogger('cbz_ui').exception('Failed to connect button click')
                            except Exception:
                                pass

            # Text nodes (Figma exports 'characters' field)
            if node.get("type") == "TEXT" or node.get("characters"):
                text = node.get("characters", "")
                lbl = QLabel(self)
                lbl.setText(text)
                lbl.setWordWrap(True)
                
                # Align text to top-left so lines start at the top of the text box
                try:
                    lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
                except Exception:
                    # fallback for PyQt versions where AlignmentFlag isn't present
                    lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)

                # Setup typing animation for all text labels: start empty and animate
                try:
                    # initialize label empty; actual typing starts when the
                    # scene becomes visible (showEvent) so all scenes type on show
                    lbl.setText("")
                    # store initial metadata so typing can be restarted later
                    self._initial_texts.append({
                        'lbl': lbl,
                        'full': text,
                        'animate_ellipsis': isinstance(text, str) and (text.rstrip().endswith('...') or text.rstrip().endswith('…')),
                    })
                except Exception:
                    lbl.setText(text)
                # determine font size if available
                font_size = node.get("fontSize") or node.get("style", {}).get("fontSize")
                font_family = None
                style = node.get("fontName") or node.get("style")
                if isinstance(style, dict):
                    font_family = style.get("family") or style.get("fontFamily")
                # Choose font family: prefer JSON's family if available, otherwise
                # use the first loaded application font from assets/fonts if any.
                chosen_family = None
                if isinstance(font_family, str) and font_family:
                    # if the requested family was registered, use it
                    if font_family in LOADED_FONT_FAMILIES:
                        chosen_family = font_family
                if not chosen_family and LOADED_FONT_FAMILIES:
                    chosen_family = LOADED_FONT_FAMILIES[0]
                f = QFont(chosen_family or (font_family or "Arial"), int(font_size) if font_size else 14)
                lbl.setFont(f)
                # Use a light color by default so text is readable on dark backgrounds.
                # If your JSON provides color information we could parse and apply it.
                # Default text color
                lbl.setStyleSheet("color: #FFFFFF;")
                # Adjust displayed height for specific prompt texts (author/series)
                display_h = max(10, int(h or 20))
                try:
                    t_low = (text or "").lower()
                    # Reduce height for author prompt and for any series prompt
                    # (use 'series' keyword to tolerate extra spaces/punctuation)
                    if "author" in t_low or "series" in t_low:
                        # reduce text block height by half to better match design
                        display_h = max(10, display_h // 2)
                except Exception:
                    pass
                # Ensure the text widget occupies the frame defined by the JSON
                lbl.setGeometry(x, y, max(10, int(w or 100)), display_h)
                # Keep text labels interactive (not mouse-transparent) so they
                # can be found/clicked if needed. But they remain read-only.
                lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                # Ensure the text label is on top of any image widgets so it's visible.
                try:
                    lbl.raise_()
                except Exception:
                    pass
                # store metadata for easy lookup/testing
                zone = {
                    "name": node.get("name") or node.get("id") or "",
                    "text": text,
                    # use display_h in the saved rect so inputs placed below
                    # reflect the reduced visual height
                    "rect": (x, y, int(w or 0), int(display_h or 0)),
                    "widget": lbl,
                }
                self.text_zones.append(zone)
                if self.DEBUG:
                    print(f"[TEXT_ZONE] scene={os.path.basename(str(self.json_path))} name={zone['name']} rect={zone['rect']} text={repr(text)[:80]}")
                    # Visual debug: draw a colored border around the text zone
                    try:
                        dbg_border = QLabel(self)
                        dbg_border.setGeometry(zone['rect'][0], zone['rect'][1], zone['rect'][2], zone['rect'][3])
                        dbg_border.setStyleSheet('background: rgba(0,0,0,0); border: 1px solid rgba(255,0,0,0.8);')
                        dbg_border.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                        dbg_border.raise_()
                        # small label with name and rect
                        info = QLabel(self)
                        info.setText(f"{zone['name']} {zone['rect']}")
                        info.setStyleSheet('background: rgba(0,0,0,0.6); color: #FF0; font-size: 10px;')
                        info.setGeometry(max(0, zone['rect'][0]), max(0, zone['rect'][1]-18), min(400, zone['rect'][2]), 16)
                        info.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                        info.raise_()
                    except Exception:
                        pass

                # If this scene is the author or series scene, create an
                # inline QLineEdit immediately under the prompt text so the
                # user can type metadata. We detect scenes by json filename
                # and by the prompt string.
                try:
                    cur_base = os.path.basename(str(self.json_path or ""))
                    # Author scene
                    if cur_base == '05_author.json' and isinstance(text, str) and "author" in text.lower():
                        # place input under the prompt box
                        ix, iy, iw, ih = zone['rect']
                        gap = 8
                        input_x = int(ix)
                        input_y = int(iy + ih + gap)
                        input_w = max(120, int(iw))
                        input_h = 40

                        class _MetaLineEdit(QLineEdit):
                            def __init__(self, parent, initial=''):
                                super().__init__(parent)
                                self._initial = initial or ''
                                self.setText(self._initial)

                            def keyPressEvent(self, ev):
                                # Intercept Enter/Return so it doesn't propagate to
                                # the MainApp keyPressEvent (which would advance
                                # the scene a second time). Accept the event
                                # after letting QLineEdit process it.
                                try:
                                    if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                                        try:
                                            super().keyPressEvent(ev)
                                        except Exception:
                                            pass
                                        try:
                                            ev.accept()
                                        except Exception:
                                            pass
                                        return
                                except Exception:
                                    pass
                                if ev.key() == Qt.Key.Key_Escape:
                                    try:
                                        self.setText(self._initial)
                                        self.clearFocus()
                                    except Exception:
                                        pass
                                    return
                                return super().keyPressEvent(ev)

                        le = _MetaLineEdit(self, initial=getattr(self.parent(), 'selected_author', '') or '')
                        le.setGeometry(input_x, input_y, input_w, input_h)
                        le.setFont(lbl.font())
                        # make visible border in debug mode to help locate the input
                        if self.DEBUG:
                            le.setStyleSheet("background: rgba(0,0,0,0.4); border: 2px dashed #00FF00; color: #FFFFFF;")
                        else:
                            le.setStyleSheet("background: transparent; border: none; color: #FFFFFF;")
                        le.setPlaceholderText("")
                        le.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                        def _save_author():
                            val = le.text().strip()
                            par = self.parent()
                            try:
                                if par is not None and hasattr(par, 'set_author'):
                                    par.set_author(val)
                                elif par is not None:
                                    setattr(par, 'selected_author', val)
                                logging.getLogger('cbz_ui').info(f"[META] author set -> {val}")
                            except Exception:
                                try:
                                    logging.getLogger('cbz_ui').exception('Failed to store author')
                                except Exception:
                                    pass

                        def _on_author_entered():
                            _save_author()
                            # try to advance to next scene for fluid UX
                            try:
                                par = self.parent()
                                if par is not None and hasattr(par, 'next_scene'):
                                    par.next_scene()
                            except Exception:
                                pass

                        le.returnPressed.connect(_on_author_entered)
                        # save on focus out as well — replace focusOutEvent with a
                        # proper wrapper that calls the original and then saves.
                        try:
                            orig_focus = le.focusOutEvent
                            def _focus_wrapper(ev):
                                try:
                                    orig_focus(ev)
                                except Exception:
                                    pass
                                try:
                                    _save_author()
                                except Exception:
                                    pass
                            le.focusOutEvent = _focus_wrapper
                        except Exception:
                            # last-resort: ignore
                            pass
                        # Auto-focus so the user can start typing without clicking.
                        try:
                            le.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                            # schedule focus after the event loop so focus is reliable
                            QTimer.singleShot(50, lambda: (le.setFocus(), le.setCursorPosition(len(le.text()))))
                        except Exception:
                            pass

                    # Series scene
                    if cur_base == '06_series.json' and isinstance(text, str) and ('series' in text.lower() or 'name of this series' in text.lower()):
                        ix, iy, iw, ih = zone['rect']
                        gap = 8
                        input_x = int(ix)
                        input_y = int(iy + ih + gap)
                        input_w = max(120, int(iw))
                        input_h = 40

                        class _SeriesLineEdit(QLineEdit):
                            def __init__(self, parent, initial=''):
                                super().__init__(parent)
                                self._initial = initial or ''
                                self.setText(self._initial)

                            def keyPressEvent(self, ev):
                                try:
                                    if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                                        try:
                                            super().keyPressEvent(ev)
                                        except Exception:
                                            pass
                                        try:
                                            ev.accept()
                                        except Exception:
                                            pass
                                        return
                                except Exception:
                                    pass
                                if ev.key() == Qt.Key.Key_Escape:
                                    try:
                                        self.setText(self._initial)
                                        self.clearFocus()
                                    except Exception:
                                        pass
                                    return
                                return super().keyPressEvent(ev)

                        le2 = _SeriesLineEdit(self, initial=getattr(self.parent(), 'selected_series', '') or '')
                        le2.setGeometry(input_x, input_y, input_w, input_h)
                        le2.setFont(lbl.font())
                        if self.DEBUG:
                            le2.setStyleSheet("background: rgba(0,0,0,0.4); border: 2px dashed #00FF00; color: #FFFFFF;")
                        else:
                            le2.setStyleSheet("background: transparent; border: none; color: #FFFFFF;")
                        le2.setPlaceholderText("")
                        le2.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                        def _save_series():
                            val = le2.text().strip()
                            par = self.parent()
                            try:
                                if par is not None and hasattr(par, 'set_series'):
                                    par.set_series(val)
                                elif par is not None:
                                    setattr(par, 'selected_series', val)
                                logging.getLogger('cbz_ui').info(f"[META] series set -> {val}")
                            except Exception:
                                try:
                                    logging.getLogger('cbz_ui').exception('Failed to store series')
                                except Exception:
                                    pass

                        def _on_series_entered():
                            _save_series()
                            try:
                                par = self.parent()
                                if par is not None and hasattr(par, 'next_scene'):
                                    par.next_scene()
                            except Exception:
                                pass

                        le2.returnPressed.connect(_on_series_entered)
                        try:
                            orig2 = le2.focusOutEvent
                            def _focus_wrapper2(ev):
                                try:
                                    orig2(ev)
                                except Exception:
                                    pass
                                try:
                                    _save_series()
                                except Exception:
                                    pass
                            le2.focusOutEvent = _focus_wrapper2
                        except Exception:
                            pass

                        # Auto-focus series input so typing works immediately.
                        try:
                            le2.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                            QTimer.singleShot(50, lambda: (le2.setFocus(), le2.setCursorPosition(len(le2.text()))))
                        except Exception:
                            pass
                        except Exception:
                            pass
                except Exception:
                    pass

            # Recurse children — pass the current node's offset so children are
            # positioned relative to the absolute coords of this node.
            for child in node.get("children", []) or []:
                # If absoluteBoundingBox was used for this node, child positions may
                # already be absolute; still passing cur_offset is safe.
                self._parse_node(child, cur_offset_x, cur_offset_y)

            # Also recurse any dict/list fields that may contain nodes (tolerant)
            for k, v in node.items():
                if k in ("children", "fills", "style"):
                    continue
                if isinstance(v, (dict, list)):
                    self._parse_node(v, cur_offset_x, cur_offset_y)

        elif isinstance(node, list):
            for item in node:
                self._parse_node(item, offset_x, offset_y)

    def _update_ellipses(self) -> None:
        """Cycle trailing dots for labels registered in _ellipsis_labels."""
        if not self._ellipsis_labels:
            try:
                if self._ellipsis_timer.isActive():
                    self._ellipsis_timer.stop()
            except Exception:
                pass
            return
        for item in list(self._ellipsis_labels):
            try:
                state = item.get('state', 1)
                state = (state % 3) + 1
                item['state'] = state
                lbl = item.get('lbl')
                prefix = item.get('prefix', '')
                try:
                    lbl.setText(prefix + ('.' * state))
                except Exception:
                    pass
            except Exception:
                pass

    def refresh_interactive_buttons(self) -> None:
        """Re-evaluate interactive overlay buttons' cursor/availability.

        This is intended to be called when metadata changes (author/series)
        so that buttons like Next become clickable once requirements are met.
        """
        try:
            parent = self.parent()
            cur_name = os.path.basename(str(self.json_path or ""))
            mapping = {
                "cbz_button.png": "02_cbz_ok.json",
                "epub_button.png": "02_epub_ok.json",
                "conversion_button.png": "08_working.json",
                "log_button.png": None,
                "next_button.png": "__NEXT__",
                "reset_button.png": "01_Home.json",
            }
            for btn in self.findChildren(HoverButton):
                try:
                    fname = getattr(btn, '_asset_name', None)
                    if not fname:
                        continue
                    target_rt = mapping.get(fname)
                    # apply same special-case routing as at click time
                    if cur_name == "02_cbz_ok.json" and fname == "epub_button.png":
                        target_rt = "03_cbz_epub_ok.json"
                    if cur_name == "02_epub_ok.json" and fname == "cbz_button.png":
                        target_rt = "03_cbz_epub_ok.json"
                    try:
                        allowed = parent.is_navigation_allowed(cur_name, target_rt, fname) if parent is not None and hasattr(parent, 'is_navigation_allowed') else True
                    except Exception:
                        allowed = True
                    # Always make log button appear clickable
                    try:
                        # Log button clickable only on final scene
                        if fname == 'log_button.png':
                            if cur_name == '09_end.json':
                                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                            else:
                                btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                        # CBZ / EPUB buttons: if parent has already selected files/folder,
                        # mark these buttons unavailable and remove hover effects
                        elif fname == 'cbz_button.png' and getattr(parent, '_cbz_selected', False):
                            try:
                                btn._hover_icon = None
                            except Exception:
                                pass
                            try:
                                btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                            except Exception:
                                pass
                        elif fname == 'epub_button.png' and getattr(parent, '_epub_selected', False):
                            try:
                                btn._hover_icon = None
                            except Exception:
                                pass
                            try:
                                btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                            except Exception:
                                pass
                        else:
                            if allowed:
                                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                            else:
                                btn.setCursor(Qt.CursorShape.ForbiddenCursor)
                    except Exception:
                        try:
                            btn.setCursor(Qt.CursorShape.ArrowCursor)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

    # Progress bar helpers (used by 08_working scene)
    def set_progress_bar(self, key: str, fraction: float) -> None:
        """Public API: request progress for a registered bar ('repaired' or 'converted').

        The call now triggers a smooth animation from the current displayed value
        to the requested fraction (0.0..1.0) instead of jumping immediately.
        """
        try:
            logger = logging.getLogger('cbz_ui')
            logger.debug(f"[PROG_UI] requested set_progress_bar key={key} frac={fraction}")
            info = self._progress_widgets.get(key)
            if not info:
                logger.debug(f"[PROG_UI] no progress widget registered for {key}")
                return
            frac = max(0.0, min(1.0, float(fraction)))
            # start a short interpolation from current to target
            try:
                self._animate_progress_to(key, frac)
            except Exception:
                # fallback to immediate apply if animation fails
                try:
                    self._apply_progress(key, frac)
                except Exception:
                    logging.getLogger('cbz_ui').exception('set_progress_bar immediate fallback failed')
        except Exception:
            logging.getLogger('cbz_ui').exception('set_progress_bar failed')

    def _apply_progress(self, key: str, frac: float) -> None:
        """Immediately render progress for key at fraction frac (0.0..1.0).

        This contains the original drawing logic extracted from the previous
        implementation. It is safe to call from the UI thread.
        """
        try:
            logger = logging.getLogger('cbz_ui')
            info = self._progress_widgets.get(key)
            if not info:
                return
            lbl = info.get('lbl')
            orig = info.get('orig_pix')
            if lbl is None or orig is None:
                return
            frac = max(0.0, min(1.0, float(frac)))
            w = orig.width()
            h = orig.height()
            if w <= 0 or h <= 0:
                return
            # create transparent pixmap and draw the bottom fraction of orig onto it
            canvas = QPixmap(w, h)
            canvas.fill(QColor(0, 0, 0, 0))
            painter = QPainter(canvas)
            try:
                src_h = int(round(frac * h))
                if src_h <= 0:
                    painter.end()
                    lbl.setPixmap(canvas)
                    try:
                        lbl.repaint()
                    except Exception:
                        pass
                    return
                src_y = h - src_h
                cropped = orig.copy(0, src_y, w, src_h)
                painter.drawPixmap(0, src_y, cropped)
            finally:
                try:
                    painter.end()
                except Exception:
                    pass
            lbl.setPixmap(canvas)
            try:
                lbl.repaint()
            except Exception:
                pass
            # No debug overlay UI: we only update the pixmap for the progress bar.
            try:
                pct = int(round(frac * 100))
                try:
                    logger.info(f"[PROG_UI] {key} {pct}%")
                except Exception:
                    pass
            except Exception:
                pass
            # persist current fraction in state
            try:
                st = self._progress_states.get(key)
                if st is None:
                    self._progress_states[key] = {'current': frac, 'timer': None}
                else:
                    st['current'] = frac
            except Exception:
                pass
        except Exception:
            logging.getLogger('cbz_ui').exception('_apply_progress failed')

    def _animate_progress_to(self, key: str, target_frac: float, duration_ms: int = 600) -> None:
        """Animate the displayed progress from current to target over duration_ms.

        Implementation uses a repeating QTimer and incremental steps so the
        visual fill appears smooth even if backend emits only coarse updates.
        """
        try:
            info = self._progress_widgets.get(key)
            if not info:
                return
            # ensure state exists
            st = self._progress_states.setdefault(key, {'current': 0.0, 'timer': None})
            current = float(st.get('current', 0.0) or 0.0)
            target = max(0.0, min(1.0, float(target_frac)))
            # Prevent visual regressions: do not animate backwards except
            # when explicitly resetting to 0.0. Many back-end emitters may
            # send slightly smaller intermediate fractions; clamp them so
            # the progress never decreases unexpectedly.
            try:
                if target < current and abs(target - 0.0) > 1e-9:
                    # ignore request to move backwards
                    target = current
            except Exception:
                pass
            if abs(target - current) < 1e-4:
                # already at target
                self._apply_progress(key, target)
                return

            # if an existing timer is running, stop and delete it
            old_timer = st.get('timer')
            if old_timer is not None:
                try:
                    old_timer.stop()
                    old_timer.deleteLater()
                except Exception:
                    pass
                st['timer'] = None

            interval = 16
            steps = max(2, int(duration_ms / interval))
            step_delta = (target - current) / float(steps)
            st['steps_left'] = steps
            st['step_delta'] = step_delta

            timer = QTimer(self)
            timer.setInterval(interval)

            def _tick():
                try:
                    if st.get('steps_left', 0) <= 1:
                        st['current'] = target
                        self._apply_progress(key, target)
                        try:
                            timer.stop()
                        except Exception:
                            pass
                        try:
                            timer.deleteLater()
                        except Exception:
                            pass
                        st['timer'] = None
                        return
                    # advance one step
                    st['current'] = float(st.get('current', 0.0)) + float(st.get('step_delta', 0.0))
                    st['steps_left'] = int(st.get('steps_left', 0)) - 1
                    self._apply_progress(key, st['current'])
                except Exception:
                    logging.getLogger('cbz_ui').exception('progress animation tick failed')

            timer.timeout.connect(_tick)
            st['timer'] = timer
            # kick off animation with an immediate tick so UI updates faster
            self._apply_progress(key, current)
            timer.start()
        except Exception:
            logging.getLogger('cbz_ui').exception('_animate_progress_to failed')

    def start_working_conversion(self, files: list[str], author: str | None, series: str | None) -> None:
        """Run a simulated conversion flow updating the progress bars.

        This runs entirely on the Qt event loop using QTimer.singleShot so
        the UI remains responsive.
        """
        try:
            if self._conversion_running:
                return
            self._conversion_running = True
            n = len(files or [])
            logger = logging.getLogger('cbz_ui')
            logger.info(f"[CONV] start conversion for {n} file(s) author={author} series={series}")

            if n == 0:
                # nothing to do — finish shortly
                QTimer.singleShot(400, lambda: self._finish_conversion())
                return

            repair_interval = 500
            convert_interval = 600

            # schedule repaired steps
            for i in range(n):
                QTimer.singleShot(i * repair_interval, lambda idx=i: self._on_repaired(idx + 1, n))

            # schedule conversion steps after all repairs
            start_conv = n * repair_interval + 300
            for i in range(n):
                QTimer.singleShot(start_conv + i * convert_interval, lambda idx=i: self._on_converted(idx + 1, n))

            # finish
            finish_at = start_conv + n * convert_interval + 400
            QTimer.singleShot(finish_at, lambda: self._finish_conversion())
        except Exception:
            logging.getLogger('cbz_ui').exception('start_working_conversion failed')

    def _on_repaired(self, count: int, total: int) -> None:
        try:
            frac = float(count) / float(total) if total else 1.0
            self.set_progress_bar('repaired', frac)
            logging.getLogger('cbz_ui').debug(f"[PROG] repaired {count}/{total} -> {frac}")
        except Exception:
            pass

    def _on_converted(self, count: int, total: int) -> None:
        try:
            frac = float(count) / float(total) if total else 1.0
            self.set_progress_bar('converted', frac)
            logging.getLogger('cbz_ui').debug(f"[PROG] converted {count}/{total} -> {frac}")
        except Exception:
            pass

    def _finish_conversion(self) -> None:
        try:
            logging.getLogger('cbz_ui').info('[CONV] finished')
            par = self.parent()
            if par is None:
                return
            # find scene 09_end.json and switch to it
            for i in range(par.count()):
                w = par.widget(i)
                jp = getattr(w, 'json_path', None)
                if isinstance(jp, str) and jp.endswith('09_end.json'):
                    try:
                        par.setCurrentIndex(i)
                    except Exception:
                        pass
                    break
        except Exception:
            logging.getLogger('cbz_ui').exception('finish_conversion failed')
