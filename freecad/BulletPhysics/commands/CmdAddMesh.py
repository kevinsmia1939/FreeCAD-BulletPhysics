import FreeCAD
import FreeCADGui

from PySide import QtWidgets


class AddMeshCommand:
    def GetResources(self):
        import os
        from .. import BulletUtils
        return {
            "Pixmap": os.path.join(BulletUtils.ICONS_PATH, "BulletMesh.svg"),
            "MenuText": "Mesh Rigid Bodies",
            "ToolTip": "Configure and generate one shared mesh for all rigid bodies.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from ..objects.BulletContainer import find_container
        from ..objects.BulletMesh import MeshSettingsPanel, make_mesh_settings

        container = find_container()
        if container is None:
            QtWidgets.QMessageBox.warning(None, "No Physics Container",
                                          "Create a Physics Container first.")
            return
        settings = getattr(container, "MeshSettings", None)
        if settings is None:
            settings = make_mesh_settings(container)
        FreeCADGui.Control.showDialog(MeshSettingsPanel(settings))


FreeCADGui.addCommand("BulletPhysics_AddMesh", AddMeshCommand())
