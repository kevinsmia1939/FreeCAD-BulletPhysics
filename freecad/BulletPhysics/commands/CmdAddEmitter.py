import FreeCAD
import FreeCADGui

from PySide import QtWidgets


def _icons_path():
    from .. import BulletUtils
    return BulletUtils.ICONS_PATH


def _selected_shape_objects():
    return [obj for obj in FreeCADGui.Selection.getSelection()
            if hasattr(obj, "Shape") and obj.Shape is not None]


class AddEmitterCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_icons_path(), "BulletLauncher.svg"),
            "MenuText": "Add Rigid Body Emitter",
            "ToolTip": (
                "Create a rigid body emitter from the selected volume or surface.\n"
                "Double-click the emitter to choose the object to emit and set timing."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and bool(_selected_shape_objects())

    def Activated(self):
        from ..objects.BulletContainer import find_container
        from ..objects.BulletEmitter import EmitterPanel, make_emitter

        source_objects = _selected_shape_objects()
        container = find_container()
        if container is None:
            QtWidgets.QMessageBox.warning(None, "No Physics Container",
                                          "Create a Physics Container first.")
            return
        if not source_objects:
            return

        doc = FreeCAD.ActiveDocument
        doc.openTransaction("Add Rigid Body Emitter")
        try:
            emitters = [make_emitter(source, container=container)
                        for source in source_objects]
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise

        if len(emitters) == 1:
            FreeCADGui.Control.showDialog(EmitterPanel(emitters[0]))


FreeCADGui.addCommand("BulletPhysics_AddEmitter", AddEmitterCommand())
