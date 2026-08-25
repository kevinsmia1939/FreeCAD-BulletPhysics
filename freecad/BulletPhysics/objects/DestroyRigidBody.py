import FreeCAD


class DestroyRigidBodyFeature:
    """Non-physical trigger that removes active bodies on contact."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "SourceObject", "Destroy Trigger",
                        "Any modelled shape used as the destruction trigger")
        obj.addProperty("App::PropertyBool", "Enabled", "Destroy Trigger",
                        "Include this trigger in Bullet Physics simulations")
        obj.Enabled = True
        obj.addProperty("App::PropertyEnumeration", "Action", "Destroy Trigger",
                        "Disable keeps the rigid-body definition; Delete removes it")
        obj.Action = ["Disable", "Delete"]
        obj.Proxy = self

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Destroy Trigger",
                            "Include this trigger in Bullet Physics simulations")
            obj.Enabled = True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class DestroyRigidBodyViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        import os
        from .. import BulletUtils
        return os.path.join(BulletUtils.ICONS_PATH, "AddDestroyBody.svg")

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_destroy_rigid_body(source_obj, container=None):
    """Create a destruction trigger for *source_obj* without changing the shape."""
    doc = FreeCAD.ActiveDocument
    obj = doc.addObject("App::FeaturePython", f"DestroyBody_{source_obj.Name}")
    DestroyRigidBodyFeature(obj)
    obj.SourceObject = source_obj
    obj.Label = f"Destroy Body: {source_obj.Label}"

    if FreeCAD.GuiUp:
        DestroyRigidBodyViewProvider(obj.ViewObject)

    if container is not None:
        if not hasattr(container, "DestroyBodies"):
            container.addProperty("App::PropertyLinkList", "DestroyBodies", "Container",
                                  "Destroy-rigid-body trigger objects")
        current = list(getattr(container, "DestroyBodies", []))
        current.append(obj)
        container.DestroyBodies = current

    doc.recompute()
    return obj
