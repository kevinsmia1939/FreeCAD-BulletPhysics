import os
import FreeCAD

MOD_PATH = os.path.dirname(os.path.dirname(__file__))


class RigidBodyFeature:
    """Stores Bullet Physics rigid body properties for a linked FreeCAD shape."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "LinkedObject", "RigidBody",
                        "The FreeCAD shape this rigid body wraps")
        obj.addProperty("App::PropertyEnumeration", "BodyType", "RigidBody",
                        "Active: moves under physics. Passive: static collider.")
        obj.BodyType = ["Active", "Passive"]
        obj.addProperty("App::PropertyFloat", "Mass", "RigidBody",
                        "Mass in kg (ignored for Passive bodies)")
        obj.Mass = 1.0
        obj.addProperty("App::PropertyFloat", "Restitution", "RigidBody",
                        "Bounciness 0 (no bounce) to 1 (perfect bounce)")
        obj.Restitution = 0.3
        obj.addProperty("App::PropertyFloat", "Friction", "RigidBody",
                        "Friction coefficient")
        obj.Friction = 0.5
        obj.Proxy = self

    def execute(self, obj):
        pass

    def onChanged(self, obj, prop):
        pass

    # Needed for document serialization
    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class RigidBodyViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        obj = self.Object
        if hasattr(obj, "BodyType") and obj.BodyType == "Passive":
            return os.path.join(MOD_PATH, "icons", "AddPassiveBody.svg")
        return os.path.join(MOD_PATH, "icons", "AddActiveBody.svg")

    def attach(self, vobj):
        self.Object = vobj.Object

    def updateData(self, obj, prop):
        pass

    def onChanged(self, vobj, prop):
        pass

    def setEdit(self, vobj, mode=0):
        return False

    def unsetEdit(self, vobj, mode=0):
        return False

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def makeRigidBody(shape_obj, body_type="Active"):
    doc = FreeCAD.ActiveDocument
    label = f"RigidBody_{shape_obj.Label}"
    obj = doc.addObject("App::FeaturePython", label)
    RigidBodyFeature(obj)
    obj.LinkedObject = shape_obj
    obj.BodyType = body_type
    obj.Label = label

    if FreeCAD.GuiUp:
        import FreeCADGui
        RigidBodyViewProvider(obj.ViewObject)
        # Grey out the original object to show it is managed
        shape_obj.ViewObject.Transparency = 30

    doc.recompute()
    return obj
