import os
import sys
import FreeCAD

from PySide.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QFileDialog, QSizePolicy,
    QCheckBox, QColorDialog,
)
from PySide.QtCore import Qt
from PySide.QtGui import QColor, QPalette


def _prefs():
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/BulletPhysics")


def get_pybullet_path():
    """Return the stored custom pybullet directory, or empty string if not set."""
    return _prefs().GetString("PybulletPath", "")


def get_event_reporting_enabled():
    """Return whether emitter and destroy-trigger events go to Report View."""
    return _prefs().GetBool("ReportEvents", False)


def _body_color(preference_name, default):
    color = QColor(_prefs().GetString(preference_name, default))
    if not color.isValid():
        color = QColor(default)
    return color


def get_body_color(body_type):
    """Return the configured RGB color tuple for an active or passive body."""
    color = _body_color(
        "PassiveBodyColor" if body_type == "Passive" else "ActiveBodyColor",
        "#4f81bd" if body_type == "Passive" else "#d65f2b")
    return (color.redF(), color.greenF(), color.blueF())


def apply_body_color(obj, body_type, refresh=False):
    """Apply the configured active/passive color to a visible document object."""
    if not FreeCAD.GuiUp or obj is None:
        return
    try:
        view_object = obj.ViewObject
        color = get_body_color(body_type)
        # App::Link inherits its source appearance unless this is enabled.
        if hasattr(view_object, "OverrideMaterial"):
            view_object.OverrideMaterial = True
        if "ShapeColor" in view_object.PropertiesList:
            view_object.ShapeColor = color

        # In current FreeCAD versions, an overridden link displays its own
        # ShapeAppearance material rather than ShapeColor.
        if hasattr(view_object, "ShapeAppearance"):
            appearance = list(view_object.ShapeAppearance)
            for material in appearance:
                material.DiffuseColor = color
            view_object.ShapeAppearance = tuple(appearance)
        elif hasattr(view_object, "ShapeMaterial"):
            view_object.ShapeMaterial.DiffuseColor = color

        if refresh:
            import FreeCADGui
            FreeCADGui.activeDocument().activeView().redraw()
    except Exception:
        pass


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
        self._active_color = _body_color("ActiveBodyColor", "#d65f2b")
        self._passive_color = _body_color("PassiveBodyColor", "#4f81bd")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self.form)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        group = QGroupBox("pybullet")
        root.addWidget(group)

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

        reporting_group = QGroupBox("Reporting")
        reporting_layout = QVBoxLayout(reporting_group)
        self._report_events_check = QCheckBox(
            "Report emitter and destroy events to the Report View")
        self._report_events_check.setToolTip(
            "Log each emitted particle and each particle disabled or deleted "
            "by a destroy rigid body trigger.")
        reporting_layout.addWidget(self._report_events_check)
        root.addWidget(reporting_group)

        colors_group = QGroupBox("Body Colors")
        colors_layout = QVBoxLayout(colors_group)
        self._active_color_button = QPushButton("Active body color")
        self._active_color_button.clicked.connect(
            lambda: self._choose_color("_active_color", self._active_color_button))
        colors_layout.addWidget(self._active_color_button)
        self._passive_color_button = QPushButton("Passive body color")
        self._passive_color_button.clicked.connect(
            lambda: self._choose_color("_passive_color", self._passive_color_button))
        colors_layout.addWidget(self._passive_color_button)
        root.addWidget(colors_group)
        root.addStretch(1)

    @staticmethod
    def _color_button_text(color):
        return color.name().upper()

    def _update_color_button(self, button, color):
        button.setText(self._color_button_text(color))
        button.setStyleSheet(
            "background-color: {}; color: {};".format(
                color.name(), "black" if color.lightness() > 128 else "white"))

    def _choose_color(self, attribute, button):
        selected = QColorDialog.getColor(getattr(self, attribute), self.form)
        if selected.isValid():
            setattr(self, attribute, selected)
            self._update_color_button(button, selected)

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
        _prefs().SetBool("ReportEvents", self._report_events_check.isChecked())
        _prefs().SetString("ActiveBodyColor", self._active_color.name())
        _prefs().SetString("PassiveBodyColor", self._passive_color.name())

    def loadSettings(self):
        self._report_events_check.setChecked(get_event_reporting_enabled())
        self._active_color = _body_color("ActiveBodyColor", "#d65f2b")
        self._passive_color = _body_color("PassiveBodyColor", "#4f81bd")
        self._update_color_button(self._active_color_button, self._active_color)
        self._update_color_button(self._passive_color_button, self._passive_color)
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
