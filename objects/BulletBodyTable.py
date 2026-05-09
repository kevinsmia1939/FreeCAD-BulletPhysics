import FreeCAD


class BulletBodyTableFeature:
    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ---------------------------------------------------------------------------
# Task panel
# ---------------------------------------------------------------------------

class BodyTablePanel:
    """Table of all rigid bodies with editable cells and bulk-apply input row."""

    COL_NAME    = 0
    COL_TYPE    = 1
    COL_DENSITY = 2
    COL_FRICT   = 3
    COL_MESH    = 4
    COL_RES     = 5

    HEADERS = [
        "Name",
        "Type",
        "Density (kg/m³)",
        "Friction",
        "Mesh Type",
        "Mesh Resolution (mm)",
    ]

    def __init__(self):
        try:
            from PySide2 import QtCore, QtWidgets
        except ImportError:
            from PySide import QtCore, QtWidgets

        self._rb_list  = []
        self._updating = False

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Rigid Body Summary")
        layout = QtWidgets.QVBoxLayout(self.form)

        # ── Table ──────────────────────────────────────────────────────────
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)   # stretch=1 → takes all surplus vertical space

        # ── Refresh ────────────────────────────────────────────────────────
        refresh_btn = QtWidgets.QPushButton("Refresh")
        try:
            refresh_btn.setIcon(
                self.form.style().standardIcon(
                    QtWidgets.QStyle.SP_BrowserReload))
        except Exception:
            pass
        layout.addWidget(refresh_btn)

        # ── Bulk-apply section ─────────────────────────────────────────────
        apply_group = QtWidgets.QGroupBox("Apply to selected rows")
        grid = QtWidgets.QGridLayout(apply_group)
        grid.setColumnStretch(1, 1)

        # Type
        grid.addWidget(QtWidgets.QLabel("Type:"), 0, 0)
        self.inp_type = QtWidgets.QComboBox()
        self.inp_type.addItems(["", "Active", "Passive"])
        self.inp_type.setToolTip("Select Active or Passive, then click Apply")
        grid.addWidget(self.inp_type, 0, 1)
        self.btn_apply_type = QtWidgets.QPushButton("Apply")
        grid.addWidget(self.btn_apply_type, 0, 2)

        # Density
        grid.addWidget(QtWidgets.QLabel("Density (kg/m³):"), 1, 0)
        self.inp_density = QtWidgets.QLineEdit()
        self.inp_density.setPlaceholderText("e.g. 7850  (steel)")
        grid.addWidget(self.inp_density, 1, 1)
        self.btn_apply_density = QtWidgets.QPushButton("Apply")
        grid.addWidget(self.btn_apply_density, 1, 2)

        # Friction
        grid.addWidget(QtWidgets.QLabel("Friction:"), 2, 0)
        self.inp_friction = QtWidgets.QLineEdit()
        self.inp_friction.setPlaceholderText("e.g. 0.5")
        grid.addWidget(self.inp_friction, 2, 1)
        self.btn_apply_friction = QtWidgets.QPushButton("Apply")
        grid.addWidget(self.btn_apply_friction, 2, 2)

        # Mesh Resolution
        grid.addWidget(QtWidgets.QLabel("Mesh Resolution (mm):"), 3, 0)
        self.inp_meshres = QtWidgets.QLineEdit()
        self.inp_meshres.setPlaceholderText("e.g. 0.5   (0 = world default)")
        self.inp_meshres.setToolTip(
            "Only applies to rows whose Mesh Type is 'mesh'.\n"
            "Set to 0 to use the Physics World default.")
        grid.addWidget(self.inp_meshres, 3, 1)
        self.btn_apply_meshres = QtWidgets.QPushButton("Apply")
        self.btn_apply_meshres.setEnabled(False)
        self.btn_apply_meshres.setToolTip(
            "Enabled when at least one selected row uses a tessellated mesh shape.")
        grid.addWidget(self.btn_apply_meshres, 3, 2)

        layout.addWidget(apply_group)

        # ── Wiring ─────────────────────────────────────────────────────────
        refresh_btn.clicked.connect(self._populate)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.btn_apply_type.clicked.connect(self._apply_type)
        self.btn_apply_density.clicked.connect(self._apply_density)
        self.btn_apply_friction.clicked.connect(self._apply_friction)
        self.btn_apply_meshres.clicked.connect(self._apply_meshres)

        self._populate()

    # ── Populate ────────────────────────────────────────────────────────────

    def _populate(self):
        try:
            from PySide2 import QtCore, QtWidgets
        except ImportError:
            from PySide import QtCore, QtWidgets

        from simulation.BulletSimulation import (
            collect_rigid_bodies, _detect_freecad_shape_type)
        from objects.BulletWorld import find_world

        self._updating = True
        try:
            world     = find_world()
            world_res = getattr(world, "MeshResolution", 1.0) if world else 1.0

            self._rb_list = collect_rigid_bodies()
            self.table.setRowCount(len(self._rb_list))

            RO = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
            ED = RO | QtCore.Qt.ItemIsEditable

            for row, rb in enumerate(self._rb_list):
                try:
                    mesh_type = _detect_freecad_shape_type(rb.OriginalObject.Shape)
                except Exception:
                    mesh_type = "unknown"

                body_res = getattr(rb, "MeshResolution", 0.0)
                if mesh_type == "mesh":
                    res_text = (f"{body_res:.3f}" if body_res > 0
                                else f"{world_res:.3f} (world)")
                else:
                    res_text = "N/A"

                density = getattr(rb, "Density", 1000.0)

                def _ro(text):
                    it = QtWidgets.QTableWidgetItem(str(text))
                    it.setFlags(RO)
                    return it

                def _ed(text):
                    it = QtWidgets.QTableWidgetItem(str(text))
                    it.setFlags(ED)
                    return it

                self.table.setItem(row, self.COL_NAME,    _ro(rb.OriginalObject.Label))
                self.table.setItem(row, self.COL_TYPE,    _ro(rb.BodyType))
                self.table.setItem(row, self.COL_DENSITY, _ed(f"{density:.2f}"))
                self.table.setItem(row, self.COL_FRICT,   _ed(f"{rb.Friction:.4f}"))
                self.table.setItem(row, self.COL_MESH,    _ro(mesh_type))
                self.table.setItem(row, self.COL_RES,     _ro(res_text))

            self.table.resizeColumnsToContents()
        finally:
            self._updating = False

    # ── Selection ───────────────────────────────────────────────────────────

    def _selected_rows(self):
        return sorted(set(idx.row() for idx in self.table.selectedIndexes()))

    def _on_selection_changed(self):
        rows = self._selected_rows()
        any_mesh = any(
            self.table.item(r, self.COL_MESH) is not None
            and self.table.item(r, self.COL_MESH).text() == "mesh"
            for r in rows
        )
        self.btn_apply_meshres.setEnabled(any_mesh)

    # ── Inline cell edit ────────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if self._updating:
            return
        row = item.row()
        col = item.column()
        if row >= len(self._rb_list):
            return
        rb = self._rb_list[row]
        try:
            if col == self.COL_DENSITY:
                rb.Density = max(0.0, float(item.text()))
            elif col == self.COL_FRICT:
                rb.Friction = max(0.0, float(item.text()))
        except ValueError:
            pass

    # ── Bulk apply ──────────────────────────────────────────────────────────

    def _apply_type(self):
        val = self.inp_type.currentText()
        if not val:
            return
        self._updating = True
        try:
            for row in self._selected_rows():
                rb = self._rb_list[row]
                rb.BodyType = val
                it = self.table.item(row, self.COL_TYPE)
                if it:
                    it.setText(val)
        finally:
            self._updating = False

    def _apply_density(self):
        try:
            val = max(0.0, float(self.inp_density.text()))
        except ValueError:
            return
        self._updating = True
        try:
            for row in self._selected_rows():
                rb = self._rb_list[row]
                rb.Density = val
                it = self.table.item(row, self.COL_DENSITY)
                if it:
                    it.setText(f"{val:.2f}")
        finally:
            self._updating = False

    def _apply_friction(self):
        try:
            val = max(0.0, float(self.inp_friction.text()))
        except ValueError:
            return
        self._updating = True
        try:
            for row in self._selected_rows():
                rb = self._rb_list[row]
                rb.Friction = val
                it = self.table.item(row, self.COL_FRICT)
                if it:
                    it.setText(f"{val:.4f}")
        finally:
            self._updating = False

    def _apply_meshres(self):
        try:
            val = max(0.0, float(self.inp_meshres.text()))
        except ValueError:
            return
        from objects.BulletWorld import find_world
        world     = find_world()
        world_res = getattr(world, "MeshResolution", 1.0) if world else 1.0

        self._updating = True
        try:
            for row in self._selected_rows():
                mesh_it = self.table.item(row, self.COL_MESH)
                if mesh_it is None or mesh_it.text() != "mesh":
                    continue
                rb = self._rb_list[row]
                rb.MeshResolution = val
                res_text = f"{val:.3f}" if val > 0 else f"{world_res:.3f} (world)"
                it = self.table.item(row, self.COL_RES)
                if it:
                    it.setText(res_text)
        finally:
            self._updating = False

    def reject(self):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()


# ---------------------------------------------------------------------------
# View provider
# ---------------------------------------------------------------------------

class BulletBodyTableViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        import os
        import BulletUtils
        return os.path.join(BulletUtils.MOD_PATH, "icons", "BulletBodyTable.svg")

    def setEdit(self, vobj, mode):
        import FreeCADGui
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Control.showDialog(BodyTablePanel())
        return True

    def unsetEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        self.setEdit(vobj, 0)
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_body_table(doc=None):
    if doc is None:
        doc = FreeCAD.ActiveDocument
    obj = doc.addObject("App::FeaturePython", "BulletBodyTable")
    BulletBodyTableFeature(obj)
    obj.Label = "Rigid Body Summary"
    if FreeCAD.GuiUp:
        import FreeCADGui
        BulletBodyTableViewProvider(obj.ViewObject)
    return obj
