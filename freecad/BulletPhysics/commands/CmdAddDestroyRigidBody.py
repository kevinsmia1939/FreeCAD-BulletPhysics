import FreeCAD
import FreeCADGui

from PySide import QtWidgets


def _icons_path():
    from .. import BulletUtils
    return BulletUtils.ICONS_PATH


def _selected_shape_objects():
    return [obj for obj in FreeCADGui.Selection.getSelection()
            if hasattr(obj, "Shape") and obj.Shape is not None]


class AddDestroyRigidBodyCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_icons_path(), "AddDestroyBody.svg"),
            "MenuText": "Add Destroy Rigid Body",
            "ToolTip": (
                "Use the selected shape as a destruction trigger.\n"
                "Active rigid bodies that touch it are disabled or deleted."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and bool(_selected_shape_objects())

    def Activated(self):
        from ..objects.BulletContainer import find_container
        from ..objects.DestroyRigidBody import make_destroy_rigid_body

        source_objects = _selected_shape_objects()
        container = find_container()
        if container is None:
            QtWidgets.QMessageBox.warning(None, "No Physics Container",
                                          "Create a Physics Container first.")
            return
        if not source_objects:
            return

        doc = FreeCAD.ActiveDocument
        doc.openTransaction("Add Destroy Rigid Body")
        try:
            for source in source_objects:
                make_destroy_rigid_body(source, container=container)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise


FreeCADGui.addCommand("BulletPhysics_AddDestroyRigidBody", AddDestroyRigidBodyCommand())
