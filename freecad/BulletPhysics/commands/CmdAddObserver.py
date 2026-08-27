import FreeCAD
import FreeCADGui

from PySide import QtWidgets


def _icons_path():
    from .. import BulletUtils
    return BulletUtils.ICONS_PATH


def _selected_shape_objects():
    return [obj for obj in FreeCADGui.Selection.getSelection()
            if hasattr(obj, "Shape") and obj.Shape is not None]


class AddObserverCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_icons_path(), "AddObserver.svg"),
            "MenuText": "Add Observer",
            "ToolTip": (
                "Use the selected volume or surface as a non-physical observer.\n"
                "Rigid bodies pass through it while their entry, exit, speed, "
                "and active/passive type are reported."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and bool(_selected_shape_objects())

    def Activated(self):
        from ..objects.BulletContainer import find_container
        from ..objects.BulletObserver import ObserverPanel, make_observer

        container = find_container()
        if container is None:
            QtWidgets.QMessageBox.warning(None, "No Physics Container",
                                          "Create a Physics Container first.")
            return
        sources = _selected_shape_objects()
        if not sources:
            return

        doc = FreeCAD.ActiveDocument
        doc.openTransaction("Add Observer")
        try:
            observers = [make_observer(source, container) for source in sources]
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        if len(observers) == 1:
            FreeCADGui.Control.showDialog(ObserverPanel(observers[0]))


FreeCADGui.addCommand("BulletPhysics_AddObserver", AddObserverCommand())
