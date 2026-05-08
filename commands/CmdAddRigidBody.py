import os
import FreeCAD
import FreeCADGui

MOD_PATH = os.path.dirname(os.path.dirname(__file__))


def _has_shape(obj):
    return hasattr(obj, "Shape") and obj.Shape is not None


def _selection_has_shapes():
    return any(_has_shape(o) for o in FreeCADGui.Selection.getSelection())


class AddActiveBodyCommand:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(MOD_PATH, "icons", "AddActiveBody.svg"),
            "MenuText": "Add Active Rigid Body",
            "ToolTip": (
                "Mark the selected solid as an active rigid body.\n"
                "Active bodies are affected by gravity and collisions."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and _selection_has_shapes()

    def Activated(self):
        from objects.RigidBody import makeRigidBody
        sel = [o for o in FreeCADGui.Selection.getSelection() if _has_shape(o)]
        if not sel:
            return
        FreeCAD.ActiveDocument.openTransaction("Add Active Rigid Body")
        for obj in sel:
            makeRigidBody(obj, "Active")
        FreeCAD.ActiveDocument.commitTransaction()


class AddPassiveBodyCommand:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(MOD_PATH, "icons", "AddPassiveBody.svg"),
            "MenuText": "Add Passive Rigid Body",
            "ToolTip": (
                "Mark the selected solid as a passive rigid body.\n"
                "Passive bodies are static colliders (e.g. a floor or wall)."
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and _selection_has_shapes()

    def Activated(self):
        from objects.RigidBody import makeRigidBody
        sel = [o for o in FreeCADGui.Selection.getSelection() if _has_shape(o)]
        if not sel:
            return
        FreeCAD.ActiveDocument.openTransaction("Add Passive Rigid Body")
        for obj in sel:
            makeRigidBody(obj, "Passive")
        FreeCAD.ActiveDocument.commitTransaction()


FreeCADGui.addCommand("BulletPhysics_AddActiveBody", AddActiveBodyCommand())
FreeCADGui.addCommand("BulletPhysics_AddPassiveBody", AddPassiveBodyCommand())
