import FreeCAD
import FreeCADGui

try:
    from PySide2.QtWidgets import QMessageBox
except ImportError:
    from PySide.QtWidgets import QMessageBox


def _mod_path():
    import BulletUtils
    return BulletUtils.MOD_PATH


def _selected_active_rigid_bodies():
    """Return selected RigidBody objects whose BodyType is Active."""
    result = []
    for obj in FreeCADGui.Selection.getSelection():
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "RigidBodyFeature"
                and getattr(obj, "BodyType", None) == "Active"):
            result.append(obj)
    return result


class AddLauncherCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "BulletLauncher.svg"),
            "MenuText": "Add Velocity Launcher",
            "ToolTip": (
                "Add a Velocity Launcher to the selected active rigid body.\n"
                "The body stays frozen until LaunchTime, then receives an\n"
                "instantaneous velocity impulse and behaves normally afterwards.\n\n"
                "Select an Active Rigid Body in the tree first."
            ),
        }

    def IsActive(self):
        return (FreeCAD.ActiveDocument is not None
                and len(_selected_active_rigid_bodies()) > 0)

    def Activated(self):
        from objects.BulletContainer import find_container
        from objects.BulletLauncher import make_launcher

        rbs = _selected_active_rigid_bodies()
        if not rbs:
            QMessageBox.warning(
                None,
                "No Active Rigid Body Selected",
                "Select one or more Active Rigid Body objects in the tree view,\n"
                "then run Add Velocity Launcher.",
            )
            return

        container = find_container()
        if container is None:
            QMessageBox.warning(
                None,
                "No Physics Container",
                "Create a Physics Container first.",
            )
            return

        FreeCAD.ActiveDocument.openTransaction("Add Velocity Launcher")
        for rb in rbs:
            make_launcher(rb, container=container)
        FreeCAD.ActiveDocument.commitTransaction()


FreeCADGui.addCommand("BulletPhysics_AddLauncher", AddLauncherCommand())
