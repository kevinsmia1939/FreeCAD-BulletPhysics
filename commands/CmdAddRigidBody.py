import FreeCAD
import FreeCADGui

try:
    from PySide2.QtWidgets import QMessageBox
except ImportError:
    from PySide.QtWidgets import QMessageBox


def _mod_path():
    import BulletUtils
    return BulletUtils.MOD_PATH


def _has_shape(obj):
    return hasattr(obj, "Shape") and obj.Shape is not None


def _selection_has_shapes():
    return any(_has_shape(o) for o in FreeCADGui.Selection.getSelection())


def _require_container():
    """Return the container or show an error and return None."""
    from objects.BulletContainer import find_container
    c = find_container()
    if c is None:
        QMessageBox.warning(
            None,
            "No Physics Container",
            "Create a Physics Container first.\n\n"
            "Use: Bullet Physics → Create Physics Container",
        )
    return c


class AddActiveBodyCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "AddActiveBody.svg"),
            "MenuText": "Add Active Rigid Body",
            "ToolTip": (
                "Mark the selected solid as an active rigid body.\n"
                "An App::Link clone is created inside the container;\n"
                "the original solid is not modified."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and _selection_has_shapes()

    def Activated(self):
        from objects.RigidBody import make_rigid_body
        container = _require_container()
        if container is None:
            return
        sel = [o for o in FreeCADGui.Selection.getSelection() if _has_shape(o)]
        if not sel:
            return
        FreeCAD.ActiveDocument.openTransaction("Add Active Rigid Body")
        for obj in sel:
            make_rigid_body(obj, "Active", container=container)
        FreeCAD.ActiveDocument.commitTransaction()


class AddPassiveBodyCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "AddPassiveBody.svg"),
            "MenuText": "Add Passive Rigid Body",
            "ToolTip": (
                "Mark the selected solid as a passive (static) rigid body.\n"
                "An App::Link clone is created inside the container;\n"
                "the original solid is not modified."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and _selection_has_shapes()

    def Activated(self):
        from objects.RigidBody import make_rigid_body
        container = _require_container()
        if container is None:
            return
        sel = [o for o in FreeCADGui.Selection.getSelection() if _has_shape(o)]
        if not sel:
            return
        FreeCAD.ActiveDocument.openTransaction("Add Passive Rigid Body")
        for obj in sel:
            make_rigid_body(obj, "Passive", container=container)
        FreeCAD.ActiveDocument.commitTransaction()


FreeCADGui.addCommand("BulletPhysics_AddActiveBody", AddActiveBodyCommand())
FreeCADGui.addCommand("BulletPhysics_AddPassiveBody", AddPassiveBodyCommand())
