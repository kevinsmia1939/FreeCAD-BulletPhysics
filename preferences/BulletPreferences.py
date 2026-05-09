import os
import sys
import FreeCAD

try:
    from PySide2.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
        QLabel, QLineEdit, QPushButton, QFileDialog, QSizePolicy,
    )
    from PySide2.QtCore import Qt
    from PySide2.QtGui import QColor, QPalette
except ImportError:
    from PySide.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
        QLabel, QLineEdit, QPushButton, QFileDialog, QSizePolicy,
    )
    from PySide.QtCore import Qt
    from PySide.QtGui import QColor, QPalette


def _prefs():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/BulletPhysics")


def get_pybullet_path():
    """Return the stored custom pybullet directory, or empty string if not set."""
    return _prefs().GetString("PybulletPath", "")


def _autodetect_pybullet():
    """Return the directory containing pybullet if importable, else empty string."""
    import importlib.util
    spec = importlib.util.find_spec("pybullet")
    if spec is not None and spec.origin:
        return os.path.dirname(os.path.abspath(spec.origin))
    return ""


def _try_import_pybullet(extra_path=""):
    """
    Try to import pybullet, optionally inserting extra_path at the front of sys.path.
    Returns (success: bool, message: str).
    """
    import importlib.util
    # Build the search path for find_spec
    search_path = list(sys.path)
    if extra_path and extra_path not in search_path:
        search_path.insert(0, extra_path)
    spec = importlib.util.find_spec("pybullet", search_path)
    if spec is None:
        return False, "pybullet not found in the specified directory or Python path"
    # Actually import to confirm it loads without error
    inserted = False
    if extra_path and extra_path not in sys.path:
        sys.path.insert(0, extra_path)
        inserted = True
    try:
        import pybullet as _pb
        version = getattr(_pb, "__version__", None)
        location = getattr(spec, "origin", "") or ""
        msg = "OK — pybullet found"
        if version:
            msg += f" (version {version})"
        if location:
            msg += f"\n{location}"
        return True, msg
    except ImportError as e:
        return False, f"Import failed: {e}"
    finally:
        if inserted and extra_path in sys.path:
            sys.path.remove(extra_path)


class BulletPreferencesPage:
    def __init__(self, parent=None):
        self.form = QWidget(parent)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self.form)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        group = QGroupBox("pybullet")
        root.addWidget(group)
        root.addStretch(1)

        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        # --- path row ---
        path_label = QLabel("pybullet directory:")
        layout.addWidget(path_label)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("(not detected — use Browse to locate pybullet)")
        self._path_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        path_row.addWidget(self._path_edit)

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        # --- help text ---
        hint = QLabel(
            "Enter the directory that contains pybullet (e.g. the site-packages folder).\n"
            "Leave empty to rely on the default Python path."
        )
        hint.setWordWrap(True)
        hint.setEnabled(False)
        layout.addWidget(hint)

        # --- check button + status ---
        check_row = QHBoxLayout()
        check_btn = QPushButton("Check pybullet")
        check_btn.setFixedWidth(130)
        check_btn.clicked.connect(self._check)
        check_row.addWidget(check_btn)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

    def _browse(self):
        current = self._path_edit.text().strip()
        start = current if current and os.path.isdir(current) else os.path.expanduser("~")
        chosen = QFileDialog.getExistingDirectory(
            self.form, "Select pybullet directory", start
        )
        if chosen:
            self._path_edit.setText(chosen)
            self._set_status("", neutral=True)

    def _check(self):
        path = self._path_edit.text().strip()
        ok, msg = _try_import_pybullet(path)
        self._set_status(msg, ok)

    def _set_status(self, text, ok=True, neutral=False):
        self._status_label.setText(text)
        if not text or neutral:
            self._status_label.setStyleSheet("")
        elif ok:
            self._status_label.setStyleSheet("color: green;")
        else:
            self._status_label.setStyleSheet("color: red;")

    def saveSettings(self):
        _prefs().SetString("PybulletPath", self._path_edit.text().strip())

    def loadSettings(self):
        stored = get_pybullet_path()
        if stored:
            self._path_edit.setText(stored)
            self._set_status("", neutral=True)
        else:
            detected = _autodetect_pybullet()
            if detected:
                self._path_edit.setText(detected)
                self._set_status("Auto-detected", ok=True)
            else:
                self._path_edit.setText("")
                self._set_status("", neutral=True)
