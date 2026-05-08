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
    """Editable table of all rigid bodies — double-click the tree item to open."""

    # Column indices
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

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        refresh_btn = QtWidgets.QPushButton("Refresh")
        try:
            refresh_btn.setIcon(
                self.form.style().standardIcon(
                    QtWidgets.QStyle.SP_BrowserReload))
        except Exception:
            pass
        layout.addWidget(refresh_btn)

        refresh_btn.clicked.connect(self._populate)
        self.table.itemChanged.connect(self._on_item_changed)

        self._populate()

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
            mesh_res  = getattr(world, "MeshResolution", 1.0) if world else 1.0

            self._rb_list = collect_rigid_bodies()
            self.table.setRowCount(len(self._rb_list))

            RO = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
            ED = RO | QtCore.Qt.ItemIsEditable

            for row, rb in enumerate(self._rb_list):
                try:
                    mesh_type = _detect_freecad_shape_type(rb.OriginalObject.Shape)
                except Exception:
                    mesh_type = "unknown"

                res_text = f"{mesh_res:.3f}" if mesh_type == "mesh" else "N/A"
                density  = getattr(rb, "Density", 1000.0)

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
        finally:
            self._updating = False

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
