import FreeCAD
import FreeCADGui


def _mod_path():
    import BulletUtils
    return BulletUtils.MOD_PATH


class CreateContainerCommand:
    def GetResources(self):
        import os
        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "BulletContainer.svg"),
            "MenuText": "Create Physics Container",
            "ToolTip": (
                "Create a Bullet Physics container with a Physics World object.\n"
                "All rigid bodies and settings are organized inside this container."
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is None:
            return False
        # Disable if a container already exists
        from objects.BulletContainer import find_container
        return find_container() is None

    def Activated(self):
        from objects.BulletContainer import make_container
        FreeCAD.ActiveDocument.openTransaction("Create Physics Container")
        make_container()
        FreeCAD.ActiveDocument.commitTransaction()


FreeCADGui.addCommand("BulletPhysics_CreateContainer", CreateContainerCommand())
