import FreeCAD


class BulletContainerFeature:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "World", "Container",
                        "Physics World settings object")
        obj.addProperty("App::PropertyLinkList", "RigidBodies", "Container",
                        "Rigid body objects managed by this simulation")
        obj.Proxy = self

    def execute(self, obj):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class BulletContainerViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        import os
        import BulletUtils
        return os.path.join(BulletUtils.MOD_PATH, "icons", "BulletContainer.svg")

    def claimChildren(self):
        obj = self.Object
        children = []
        if hasattr(obj, "World") and obj.World is not None:
            children.append(obj.World)
        if hasattr(obj, "RigidBodies"):
            children.extend(rb for rb in obj.RigidBodies if rb is not None)
        return children

    def onDelete(self, vobj, subelements):
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def find_container(doc=None):
    """Return the first BulletContainer in the document, or None."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return None
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletContainerFeature"):
            return obj
    return None


def make_container(doc=None):
    if doc is None:
        doc = FreeCAD.ActiveDocument

    from objects.BulletWorld import BulletWorldFeature, BulletWorldViewProvider

    # Container
    container = doc.addObject("App::FeaturePython", "BulletPhysics")
    BulletContainerFeature(container)
    container.Label = "Bullet Physics"

    # World inside container
    world = doc.addObject("App::FeaturePython", "BulletWorld")
    BulletWorldFeature(world)
    world.Label = "Physics World"

    container.World = world

    if FreeCAD.GuiUp:
        import FreeCADGui
        BulletContainerViewProvider(container.ViewObject)
        BulletWorldViewProvider(world.ViewObject)

    doc.recompute()
    return container
