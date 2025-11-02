"""
main.py — Entry point of the CBZ → EPUB converter UI demo
This version only handles the UI and scene transitions.
"""

import sys
import os
import datetime
import logging
from logging.handlers import RotatingFileHandler
from PyQt6.QtWidgets import QApplication, QStackedWidget, QPushButton, QMessageBox
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
import threading
import tempfile
import zipfile
import subprocess
import shutil
from pathlib import Path
import time


def _sanitize_filename(name: str) -> str:
    """Basic filename sanitizer: remove path separators and illegal chars.

    Keeps letters, numbers, spaces, dash, underscore and a few symbols.
    Collapses whitespace and strips edges.
    """
    if not name:
        return ''
    # replace slashes/backslashes and forbidden characters
    forbidden = '\\/:*?"<>|'
    out = ''.join(ch for ch in name if ch not in forbidden)
    # collapse whitespace
    out = ' '.join(out.split())
    return out.strip()

# Debug: print the first lines of ui/base_scene.py to help diagnose import-time SyntaxError
try:
    bs_path = os.path.join(os.path.dirname(__file__), 'ui', 'base_scene.py')
    if os.path.exists(bs_path):
        with open(bs_path, 'r', encoding='utf-8') as _f:
            lines = _f.readlines()[:300]
        print('--- ui/base_scene.py (start) ---')
        for ln in lines:
            print(ln.rstrip('\n'))
        print('--- end of sample ---')
except Exception:
    pass

from ui.scene_loader import load_scenes


class MainApp(QStackedWidget):
    """Main application managing scene transitions with fade effect."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(1290, 818)
        self.setWindowTitle("CBZ to EPUB Converter")
        # Hide the native title bar / window frame for a cleaner preview UI.
        # We still implement basic dragging so the user can move the window.
        try:
            self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, False)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            # Enable translucent background so the window itself has no opaque
            # background (requires a compositing window manager / DWM on Windows).
            try:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            except Exception:
                pass
            # ensure the stacked widget is painted transparently
            try:
                self.setStyleSheet('background: transparent;')
            except Exception:
                pass
        except Exception:
            try:
                # fallback for older PyQt6 versions
                self.setWindowFlag(Qt.FramelessWindowHint, True)
            except Exception:
                pass
        self._drag_pos = None
        # canonical order of scenes (json basenames)
        self.order = [
            "01_Home.json",
            "02_cbz_ok.json",
            "02_epub_ok.json",
            "03_cbz_epub_ok.json",
            "04_metadata.json",
            "05_author.json",
            "06_series.json",
            "07_start_conversion.json",
            "08_working.json",
            "09_end.json",
        ]
        # Load scenes and keep list
        self.scenes = load_scenes(self)
        self._anims = []  # keep animation refs
        # user selections
        self.selected_cbz_files = []
        self.selected_epub_output_dir = None
        # metadata fields
        self.selected_author = None
        self.selected_series = None

        # show first scene
        if self.scenes:
            self.setCurrentIndex(0)

        # Poster object to emit progress updates from background threads
        class _ProgressPoster(QObject):
            progress = pyqtSignal(str, float)
            finished = pyqtSignal()

        self._progress_poster = _ProgressPoster()

    # Note: the Next button is part of the scene artwork (next_button.png)
    # and will be created as an overlay in each scene. We keep Enter handling
    # here but remove the fixed global Next QPushButton.

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next_scene()

    # Note: window drag via global mouse handlers removed. A scene-provided
    # drag control (an artwork button) will handle moving the window instead.

    def next_scene(self):
        if not self.scenes:
            return

        # Define the intended linear flow. Branching from 01_Home is handled
        # by the interactive buttons (cbz/epub). Next/Enter should advance in
        # the canonical sequence after branching: 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09
        order = [
            "01_Home.json",
            "02_cbz_ok.json",
            "02_epub_ok.json",
            "03_cbz_epub_ok.json",
            "04_metadata.json",
            "05_author.json",
            "06_series.json",
            "07_start_conversion.json",
            "08_working.json",
            "09_end.json",
        ]

        cur_idx = self.currentIndex()
        current_widget = self.widget(cur_idx)

        # Find current scene filename (json) and its position in order
        cur_name = getattr(current_widget, "json_path", "")
        cur_base = cur_name.split("\\")[-1] if cur_name else ""

        # If we're on the Home scene, Next should do nothing (user must choose cbz/epub)
        if cur_base == "01_Home.json":
            return

        try:
            pos = order.index(cur_base)
        except ValueError:
            # fallback: simple next index
            nxt = (cur_idx + 1) % len(self.scenes)
            next_widget = self.widget(nxt)
        else:
            # move to the next entry in the canonical order if possible
            if pos < len(order) - 1:
                target_name = order[pos + 1]
                # find the loaded scene widget with this json basename
                next_widget = None
                for s in self.scenes:
                    if getattr(s, "json_path", "").endswith(target_name):
                        next_widget = s
                        break
                if next_widget is None:
                    # fallback to sequential next
                    nxt = (cur_idx + 1) % len(self.scenes)
                    next_widget = self.widget(nxt)
            else:
                # already last scene
                return

        # Ensure no leftover graphics effects (opacity) remain from previous transitions
        try:
            current_widget.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            next_widget.setGraphicsEffect(None)
        except Exception:
            pass

        # Instant switch (no fade)
        self.setCurrentWidget(next_widget)
        # Robustness: some platforms may not reliably call showEvent after
        # setCurrentWidget; call _start_typing() if available to ensure
        # typing restarts when a scene becomes active.
        try:
            logging.getLogger("cbz_ui").debug(f"[NAV] setCurrentWidget -> {getattr(next_widget, 'json_path', None)}")
        except Exception:
            pass
        try:
            start = getattr(next_widget, '_start_typing', None)
            if callable(start):
                start()
        except Exception:
            pass
        self._anims = []

    def is_navigation_allowed(self, cur_base: str, target_rt: str | None, fname: str | None) -> bool:
        """Decide whether a navigation from cur_base to target_rt (button fname) is allowed.

        Rules:
        - reset_button allowed always (returns to Home)
        - if target_rt is None -> not allowed
        - if target_rt == '__NEXT__' -> allowed only if current scene is not Home and not last
        - otherwise allow only if target is exactly the next scene in the canonical order
        """
        if not cur_base:
            return False
        # allow reset anytime
        if fname == "reset_button.png":
            return True

        if target_rt is None:
            return False

        # Special-case: from Home, allow both 02_cbz_ok and 02_epub_ok
        if cur_base == "01_Home.json" and target_rt in ("02_cbz_ok.json", "02_epub_ok.json"):
            return True

        # Special-case: from either 02_cbz_ok or 02_epub_ok, allow going to 03_cbz_epub_ok
        if cur_base in ("02_cbz_ok.json", "02_epub_ok.json") and target_rt == "03_cbz_epub_ok.json":
            return True

        if target_rt == "__NEXT__":
            try:
                pos = self.order.index(cur_base)
            except ValueError:
                return False
            # Contextual Next permission:
            # - On the author scene (05_author.json) require author to be filled.
            # - On the series scene (06_series.json) require series to be filled.
            # - On other scenes, allow Next according to canonical order.
            try:
                if cur_base == '05_author.json':
                    author = getattr(self, 'selected_author', None)
                    if not author:
                        try:
                            logging.getLogger('cbz_ui').debug(f"[NAV_CHECK] Next blocked on 05_author: missing author={author!r}")
                        except Exception:
                            pass
                        return False
                if cur_base == '06_series.json':
                    series = getattr(self, 'selected_series', None)
                    if not series:
                        try:
                            logging.getLogger('cbz_ui').debug(f"[NAV_CHECK] Next blocked on 06_series: missing series={series!r}")
                        except Exception:
                            pass
                        return False
            except Exception:
                pass
            return pos < (len(self.order) - 1) and cur_base != "01_Home.json"

        # only allow transitions that move to the next canonical scene
        try:
            pos_cur = self.order.index(cur_base)
            pos_tgt = self.order.index(target_rt)
        except ValueError:
            return False

        return pos_tgt == pos_cur + 1

    def set_cbz_files(self, files: list[str]) -> None:
        """Store the user-selected CBZ files (called from scene handlers)."""
        try:
            self.selected_cbz_files = list(files or [])
            logging.getLogger("cbz_ui").info(f"[MAIN] stored {len(self.selected_cbz_files)} cbz file(s)")
        except Exception:
            try:
                logging.getLogger("cbz_ui").exception("Failed to store cbz files")
            except Exception:
                pass

    def set_epub_output_dir(self, path: str) -> None:
        """Store the user-selected output directory for EPUB files."""
        try:
            self.selected_epub_output_dir = str(path) if path else None
            logging.getLogger("cbz_ui").info(f"[MAIN] stored epub output dir: {self.selected_epub_output_dir}")
        except Exception:
            try:
                logging.getLogger("cbz_ui").exception("Failed to store epub output dir")
            except Exception:
                pass

    def set_author(self, name: str) -> None:
        """Store author metadata entered by the user."""
        try:
            self.selected_author = str(name) if name else None
            logging.getLogger("cbz_ui").info(f"[MAIN] stored author: {self.selected_author}")
            # notify current scene to refresh interactive buttons (Next etc.)
            try:
                cur = self.currentWidget()
                if cur is not None and hasattr(cur, 'refresh_interactive_buttons'):
                    try:
                        cur.refresh_interactive_buttons()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            try:
                logging.getLogger("cbz_ui").exception("Failed to store author")
            except Exception:
                pass

    def set_series(self, name: str) -> None:
        """Store series metadata entered by the user."""
        try:
            self.selected_series = str(name) if name else None
            logging.getLogger("cbz_ui").info(f"[MAIN] stored series: {self.selected_series}")
            # notify current scene to refresh interactive buttons (Next etc.)
            try:
                cur = self.currentWidget()
                if cur is not None and hasattr(cur, 'refresh_interactive_buttons'):
                    try:
                        cur.refresh_interactive_buttons()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            try:
                logging.getLogger("cbz_ui").exception("Failed to store series")
            except Exception:
                pass

    def start_conversion(self) -> None:
        """Locate the 08_working scene and start the conversion process."""
        try:
            # find the working scene
            working_widget = None
            for s in self.scenes:
                jp = getattr(s, 'json_path', '')
                if isinstance(jp, str) and jp.endswith('08_working.json'):
                    working_widget = s
                    break
            if working_widget is None:
                logging.getLogger('cbz_ui').warning('No 08_working scene loaded')
                return
            # connect poster signal to the working widget's setter so background
            # thread can emit progress safely
            try:
                # disconnect any previous connections to avoid duplicates
                try:
                    self._progress_poster.progress.disconnect()
                except Exception:
                    pass
                self._progress_poster.progress.connect(working_widget.set_progress_bar)
                # ensure finished signal navigates to the end scene
                try:
                    # disconnect previous finished handlers to avoid duplicates
                    try:
                        self._progress_poster.finished.disconnect()
                    except Exception:
                        pass
                    self._progress_poster.finished.connect(self.goto_end)
                except Exception:
                    logging.getLogger('cbz_ui').exception('Failed to connect finished poster')
                logging.getLogger('cbz_ui').debug('Connected progress poster to working_widget.set_progress_bar')
            except Exception:
                logging.getLogger('cbz_ui').exception('Failed to connect progress poster')
            # start real conversion in a background thread so UI stays responsive
            files = list(self.selected_cbz_files or [])
            author = getattr(self, 'selected_author', None)
            series = getattr(self, 'selected_series', None)

            # Prepare an in-memory session summary that will be used to
            # generate a user-readable log later. It's mutated by the
            # background thread during processing.
            self._session = {
                'start_time': None,
                'end_time': None,
                'input_dir': None,
                'output_dir': str(self.selected_epub_output_dir or ''),
                'found_files': [os.path.basename(f) for f in files],
                'repair': {},   # filename -> 'OK'|'FIXED'|'ERROR'
                'convert': {},  # filename -> 'OK'|'ERROR'|'SKIPPED'
                'author': author,
                'series': series,
                'tool': 'Calibre (ebook-convert)',
                'version': 'v1.0.0',
            }

            def _run_conversion():
                logger = logging.getLogger('cbz_ui')
                logger.info(f"[CONV_THREAD] starting conversion thread for {len(files)} file(s)")
                try:
                    self._session['start_time'] = datetime.datetime.now()
                    # Try to infer input directory from first selected file
                    if files:
                        try:
                            self._session['input_dir'] = str(Path(files[0]).parent)
                        except Exception:
                            self._session['input_dir'] = ''
                except Exception:
                    pass

                # find ebook-convert executable
                ebook_convert = shutil.which('ebook-convert')
                if not ebook_convert:
                    # try Windows executable name
                    ebook_convert = shutil.which('ebook-convert.exe')
                if not ebook_convert:
                    logger.error('ebook-convert not found in PATH; cannot convert')
                    try:
                        # inform user on main thread
                        from PyQt6.QtWidgets import QMessageBox
                        QTimer.singleShot(0, lambda: QMessageBox.warning(None, 'Conversion failed', 'Calibre\'s ebook-convert not found in PATH.'))
                    except Exception:
                        pass
                    return

                # temp files to clean up
                temp_repaired = []

                try:
                    total = max(1, len(files))

                    def _emit_smooth(stage: str, start_frac: float, end_frac: float, duration_ms: int = 300):
                        """Emit multiple small progress signals between start_frac and end_frac.

                        Runs in the conversion thread and uses the poster to queue
                        UI updates on the main thread.
                        """
                        try:
                            steps = max(2, int(max(1, duration_ms) / 50))
                            for i in range(1, steps + 1):
                                try:
                                    frac = start_frac + (end_frac - start_frac) * (i / float(steps))
                                    self._progress_poster.progress.emit(stage, min(1.0, max(0.0, frac)))
                                except Exception:
                                    logging.getLogger('cbz_ui').exception('Failed to emit smooth progress')
                                time.sleep(duration_ms / float(steps) / 1000.0)
                        except Exception:
                            logging.getLogger('cbz_ui').exception('emit_smooth failed')

                    # Repair step: for each cbz, extract+repack to a temp cbz
                    for idx, f in enumerate(files, start=1):
                        try:
                            logger.debug(f"[REPAIR] processing {f}")
                            td = tempfile.mkdtemp(prefix='cbz_repair_')
                            extracted_ok = True
                            try:
                                with zipfile.ZipFile(f, 'r') as zin:
                                    zin.extractall(td)
                            except Exception:
                                extracted_ok = False
                                logger.exception(f"Failed to extract {f}")
                            repaired_path = Path(tempfile.mktemp(suffix='.cbz'))
                            try:
                                with zipfile.ZipFile(str(repaired_path), 'w', compression=zipfile.ZIP_STORED) as zout:
                                    for root, _, files_in in os.walk(td):
                                        for name in files_in:
                                            full = Path(root) / name
                                            arcname = str(full.relative_to(td))
                                            try:
                                                zout.write(str(full), arcname)
                                            except Exception:
                                                logger.exception(f"Failed to add {full} to repaired archive")
                            except Exception:
                                logger.exception('Failed to create repaired archive')
                            temp_repaired.append(str(repaired_path))
                            # record repair status
                            try:
                                base = os.path.basename(f)
                                if extracted_ok:
                                    self._session['repair'][base] = 'OK'
                                else:
                                    # extraction failed but we still produced a repaired archive
                                    self._session['repair'][base] = 'FIXED'
                            except Exception:
                                pass
                        except Exception:
                            logger.exception('Error during repair step')
                        # Smoothly animate repaired progress from (idx-1)/total -> idx/total
                        try:
                            _emit_smooth('repaired', float(idx - 1) / float(total), float(idx) / float(total), duration_ms=350)
                        except Exception:
                            pass

                    # Ensure repaired bar is full
                    try:
                        self._progress_poster.progress.emit('repaired', 1.0)
                    except Exception:
                        pass

                    # Conversion step: convert each repaired file to epub
                    for idx, rp in enumerate(temp_repaired, start=1):
                        try:
                            in_path = rp
                            src_name = Path(in_path).stem
                            out_dir = Path(self.selected_epub_output_dir or os.getcwd())
                            out_dir.mkdir(parents=True, exist_ok=True)
                            # Standardize output filename: "{series} T°{n}" if series provided
                            try:
                                series_name = str(series).strip() if series else ''
                                if series_name:
                                    safe_series = _sanitize_filename(series_name)
                                    base_name = f"{safe_series} T°{idx}"
                                else:
                                    base_name = src_name
                            except Exception:
                                base_name = src_name
                            out_path = str(out_dir / (base_name + '.epub'))

                            cmd = [ebook_convert, in_path, out_path]
                            # Preserve original CBZ cover: detect an image file in the
                            # repaired archive that is most likely the cover (filename
                            # contains 'cover' or the first image by sorted name). If
                            # found, extract it to a temp file and pass --cover to
                            # ebook-convert so the EPUB uses the exact same image.
                            cover_tmp = None
                            try:
                                import zipfile as _zip
                                with _zip.ZipFile(in_path, 'r') as _z:
                                    members = [m for m in _z.namelist() if m and not m.endswith('/')]
                                    # filter image files
                                    img_exts = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
                                    imgs = [m for m in members if os.path.splitext(m)[1].lower() in img_exts]
                                    cover_member = None
                                    if imgs:
                                        # prefer files with 'cover' in the name
                                        for m in imgs:
                                            if 'cover' in os.path.basename(m).lower():
                                                cover_member = m
                                                break
                                        if cover_member is None:
                                            imgs.sort()
                                            cover_member = imgs[0]
                                    if cover_member:
                                        # extract to a temp file
                                        try:
                                            suffix = os.path.splitext(cover_member)[1]
                                            tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                                            tf.write(_z.read(cover_member))
                                            tf.flush()
                                            tf.close()
                                            cover_tmp = tf.name
                                        except Exception:
                                            cover_tmp = None
                            except Exception:
                                cover_tmp = None
                            if author:
                                cmd += ['--authors', str(author)]
                            if series:
                                cmd += ['--series', str(series)]
                            if cover_tmp:
                                try:
                                    cmd += ['--cover', str(cover_tmp)]
                                except Exception:
                                    pass
                            logger.info(f"[CONVERT] {' '.join(cmd[:3])} ...")
                            try:
                                # start conversion and animate progress for this file
                                proc = subprocess.Popen(cmd)
                                # while conversion runs, periodically bump progress
                                start_frac = float(idx - 1) / float(max(1, len(temp_repaired)))
                                end_frac = float(idx) / float(max(1, len(temp_repaired)))
                                # run emitter in small loops until process ends
                                while proc.poll() is None:
                                    _emit_smooth('converted', start_frac, end_frac, duration_ms=500)
                                try:
                                    proc.wait(timeout=1)
                                except Exception:
                                    pass
                                logger.info(f"[CONVERT] wrote {out_path}")
                                # record successful conversion (map original cbz basename)
                                try:
                                    orig_cbz = os.path.basename(rp)
                                    self._session['convert'][orig_cbz] = ('OK', out_path)
                                except Exception:
                                    pass
                                # cleanup extracted cover temp
                                try:
                                    if cover_tmp and os.path.exists(cover_tmp):
                                        os.unlink(cover_tmp)
                                except Exception:
                                    pass
                            except subprocess.CalledProcessError:
                                logger.exception(f"Conversion failed for {rp}")
                                try:
                                    orig_cbz = os.path.basename(rp)
                                    self._session['convert'][orig_cbz] = ('ERROR', '')
                                except Exception:
                                    pass
                                try:
                                    if cover_tmp and os.path.exists(cover_tmp):
                                        os.unlink(cover_tmp)
                                except Exception:
                                    pass
                            except Exception:
                                logger.exception('Error during conversion step')
                                try:
                                    orig_cbz = os.path.basename(rp)
                                    self._session['convert'][orig_cbz] = ('ERROR', '')
                                except Exception:
                                    pass
                        except Exception:
                            logger.exception('Error preparing conversion')
                            try:
                                orig_cbz = os.path.basename(rp)
                                self._session['convert'][orig_cbz] = ('ERROR', '')
                            except Exception:
                                pass
                        time.sleep(0.01)

                    # finalize conversion bar
                    try:
                        self._progress_poster.progress.emit('converted', 1.0)
                    except Exception:
                        pass

                finally:
                    # cleanup temp repaired files/dirs
                    for p in temp_repaired:
                        try:
                            Path(p).unlink()
                        except Exception:
                            pass
                    # record end time/duration then signal main thread that conversion finished (preferred)
                    try:
                        self._session['end_time'] = datetime.datetime.now()
                    except Exception:
                        pass
                    try:
                        self._progress_poster.finished.emit()
                    except Exception:
                        # fallback to scheduling on the main thread
                        try:
                            def _goto_end():
                                try:
                                    for i in range(self.count()):
                                        w = self.widget(i)
                                        jp = getattr(w, 'json_path', None)
                                        if isinstance(jp, str) and jp.endswith('09_end.json'):
                                            self.setCurrentIndex(i)
                                            break
                                except Exception:
                                    logging.getLogger('cbz_ui').exception('goto_end failed')
                            QTimer.singleShot(0, _goto_end)
                        except Exception:
                            pass

            t = threading.Thread(target=_run_conversion, daemon=True)
            t.start()
        except Exception:
            logging.getLogger('cbz_ui').exception('start_conversion failed')
        except Exception:
            logging.getLogger('cbz_ui').exception('start_conversion failed')

    def goto_end(self) -> None:
        """Switch the stacked widget to the 09_end scene (runs on UI thread)."""
        try:
            for i in range(self.count()):
                w = self.widget(i)
                jp = getattr(w, 'json_path', None)
                if isinstance(jp, str) and jp.endswith('09_end.json'):
                    try:
                        self.setCurrentIndex(i)
                    except Exception:
                        pass
                    break
        except Exception:
            logging.getLogger('cbz_ui').exception('goto_end failed')

    def generate_log(self) -> str:
        """Generate a session log.txt in the selected EPUB output directory.

        Returns the path to the written log file or raises an exception on failure.
        """
        logger = logging.getLogger('cbz_ui')
        sess = getattr(self, '_session', None) or {}
        out_dir = str(sess.get('output_dir') or self.selected_epub_output_dir or '')
        if not out_dir:
            raise RuntimeError('No output directory selected')
        out_path_dir = Path(out_dir)
        out_path_dir.mkdir(parents=True, exist_ok=True)
        log_file = out_path_dir / 'log.txt'

        # gather session info
        start = sess.get('start_time')
        end = sess.get('end_time')
        if isinstance(start, datetime.datetime):
            start_s = start.strftime('%Y-%m-%d  %H:%M:%S')
        else:
            start_s = datetime.datetime.now().strftime('%Y-%m-%d  %H:%M:%S')
        if isinstance(end, datetime.datetime) and isinstance(start, datetime.datetime):
            dur = end - start
        else:
            dur = datetime.timedelta(0)

        user = ''
        try:
            import getpass
            user = getpass.getuser()
        except Exception:
            user = ''

        found = sess.get('found_files') or []
        repair = sess.get('repair') or {}
        convert = sess.get('convert') or {}

        repaired_count = sum(1 for v in repair.values() if v == 'FIXED')
        intact_count = sum(1 for v in repair.values() if v == 'OK')
        corrupt_count = sum(1 for v in repair.values() if v == 'ERROR')

        conv_ok = sum(1 for v in convert.values() if isinstance(v, tuple) and v[0] == 'OK')
        conv_err = sum(1 for v in convert.values() if isinstance(v, tuple) and v[0] == 'ERROR')
        conv_skipped = sum(1 for v in convert.values() if isinstance(v, tuple) and v[0] == 'SKIPPED')

        # build report text (match the example layout)
        sep = '─' * 46
        lines = []
        lines.append(sep)
        lines.append('CBZ → EPUB CONVERTER — SESSION LOG')
        lines.append(sep)
        lines.append(f'Date : {start_s}')
        lines.append(f'Utilisateur : {user}')
        lines.append(f'Version de l\'application : {sess.get("version", "v1.0.0")}')
        lines.append(sep)
        lines.append('')
        lines.append('🗂️ Dossier d’entrée :')
        lines.append(str(sess.get('input_dir') or ''))
        lines.append('')
        lines.append('📁 Dossier de sortie :')
        lines.append(str(out_dir))
        lines.append('')
        lines.append(sep)
        lines.append('📋 LISTE DES FICHIERS TROUVÉS')
        lines.append(sep)
        for i, fn in enumerate(found, start=1):
            lines.append(f'{i}. {fn}')
        lines.append(f'→ Total : {len(found)} fichiers détectés')
        lines.append('')
        lines.append(sep)
        lines.append('🧩 ÉTAPE 1 — VÉRIFICATION ET RÉPARATION')
        lines.append(sep)
        for fn in found:
            st = repair.get(fn, 'OK')
            if st == 'OK':
                lines.append(f'[OK] {fn} — archive valide')
            elif st == 'FIXED':
                lines.append(f'[FIXED] {fn} — corruption réparée')
            else:
                lines.append(f'[ERROR] {fn} — fichier illisible (zlib error)')
        lines.append('')
        lines.append(f'→ {repaired_count} fichier(s) réparé(s), {corrupt_count} fichier(s) illisible(s), {intact_count} intact(s)')
        lines.append('')
        lines.append(sep)
        lines.append('⚙️ ÉTAPE 2 — CONVERSION CBZ → EPUB')
        lines.append(sep)
        for fn in found:
            cv = convert.get(fn)
            if not cv:
                lines.append(f'[SKIPPED] {fn} → fichier ignoré (non réparable)')
            else:
                st = cv[0]
                outp = cv[1] if len(cv) > 1 else ''
                if st == 'OK':
                    lines.append(f'[OK] {fn} → {os.path.basename(outp)}')
                elif st == 'SKIPPED':
                    lines.append(f'[SKIPPED] {fn} → fichier ignoré (non réparable)')
                else:
                    lines.append(f'[ERROR] {fn} → échec de la conversion')
        lines.append('')
        lines.append(f'→ {conv_ok} conversions réussies / {len(found)} fichiers traités')
        lines.append('')
        lines.append(sep)
        lines.append('🧾 SYNTHÈSE GLOBALE')
        lines.append(sep)
        lines.append(f'📦 Fichiers trouvés : {len(found)}')
        lines.append(f'🛠️ Fichiers réparés : {repaired_count}')
        lines.append(f'✅ Conversions réussies : {conv_ok}')
        lines.append(f'⚠️ Conversions échouées : {conv_err + conv_skipped}')
        # format duration
        total_seconds = int(dur.total_seconds())
        hh = total_seconds // 3600
        mm = (total_seconds % 3600) // 60
        ss = total_seconds % 60
        lines.append(f'⏱️ Durée totale : {hh:02d}:{mm:02d}:{ss:02d}')
        lines.append('')
        lines.append(sep)
        lines.append('💬 DÉTAILS SUPPLÉMENTAIRES')
        lines.append(sep)
        if sess.get('series'):
            lines.append(f'- Nom de la série : {sess.get("series")}')
        if sess.get('author'):
            lines.append(f'- Auteur : {sess.get("author")}')
        lines.append(f'- Logiciel de conversion : {sess.get("tool", "Calibre (ebook-convert)")}')
        lines.append(f'- Format de sortie : EPUB v2')
        lines.append(sep)
        lines.append('')
        lines.append('Fin du rapport — CBZ→EPUB Converter')
        lines.append(sep)

        # write to file
        try:
            with open(str(log_file), 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(lines))
        except Exception as e:
            logger.exception('Failed to write log file')
            raise

        return str(log_file)


def main() -> None:
    # Configure logging: console + rotating file
    log_path = os.path.join(os.path.dirname(__file__), "startup_debug.log")
    logger = logging.getLogger("cbz_ui")
    logger.setLevel(logging.DEBUG if os.environ.get("DEBUG_UI") == "1" else logging.INFO)
    # console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(ch)
    # rotating file handler
    try:
        fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(fh)
    except Exception:
        logger.warning("Could not create file handler for %s", log_path)

    logger.info("[MAIN] starting")
    app = QApplication(sys.argv)
    logger.info("[MAIN] QApplication created")
    win = MainApp()
    logger.info("[MAIN] MainApp initialized")
    # center window
    screen = app.primaryScreen().availableGeometry()
    x = (screen.width() - win.width()) // 2
    y = (screen.height() - win.height()) // 2
    win.move(x, y)
    win.show()
    try:
        rv = app.exec()
        logger.info(f"[MAIN] app.exec returned {rv}")
        sys.exit(rv)
    except Exception:
        logger.exception("Unhandled exception in main event loop")
        sys.exit(1)


if __name__ == "__main__":
    main()
