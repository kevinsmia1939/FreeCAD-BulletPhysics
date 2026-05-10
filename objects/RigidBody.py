import FreeCAD


class RigidBodyFeature:
    """
    Stores Bullet Physics properties for one solid.
    The simulation drives BodyLink (App::Link), leaving OriginalObject untouched.
    """

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "OriginalObject", "RigidBody",
                        "The original FreeCAD solid (never modified)")
        obj.addProperty("App::PropertyLink", "BodyLink", "RigidBody",
                        "App::Link clone — simulation moves this")
        obj.addProperty("App::PropertyEnumeration", "BodyType", "RigidBody",
                        "Active: moved by physics.  Passive: static collider.")
        obj.BodyType = ["Active", "Passive"]
        obj.addProperty("App::PropertyFloat", "Density", "RigidBody",
                        "Material density in kg/m³. Mass is computed automatically "
                        "as density × shape volume. Ignored for Passive bodies.")
        obj.Density = 1000.0
        obj.addProperty("App::PropertyFloat", "Restitution", "RigidBody",
                        "Bounciness 0 (none) → 1 (perfect)")
        obj.Restitution = 0.3
        obj.addProperty("App::PropertyFloat", "Friction", "RigidBody",
                        "Friction coefficient")
        obj.Friction = 0.5
        obj.addProperty("App::PropertyFloat", "MeshResolution", "RigidBody",
                        "Tessellation chord deviation in mm for this body's mesh collision "
                        "shape. 0 = use Physics World default. Ignored for primitives.")
        obj.MeshResolution = 0.0
        obj.addProperty("App::PropertyEnumeration", "ShapeOverride", "RigidBody",
                        "Override the auto-detected collision shape type. "
                        "'Auto' uses the shape detected from geometry. "
                        "'mesh' = concave BVH (static only). "
                        "'convex_hull' = convex hull (works for dynamic bodies).")
        obj.ShapeOverride = ["Auto", "box", "sphere", "cylinder", "convex_hull", "mesh"]
        obj.Proxy = self

    def execute(self, obj):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class RigidBodyViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self
        vobj.Visibility = True

    def attach(self, vobj):
        self.Object = vobj.Object
        vobj.Visibility = True

    def getIcon(self):
        import os
        import BulletUtils
        obj = self.Object
        name = ("AddPassiveBody.svg"
                if hasattr(obj, "BodyType") and obj.BodyType == "Passive"
                else "AddActiveBody.svg")
        return os.path.join(BulletUtils.MOD_PATH, "icons", name)

    def claimChildren(self):
        obj = self.Object
        if hasattr(obj, "BodyLink") and obj.BodyLink is not None:
            return [obj.BodyLink]
        return []

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            obj = self.Object
            if hasattr(obj, "BodyLink") and obj.BodyLink is not None:
                try:
                    obj.BodyLink.ViewObject.Visibility = vobj.Visibility
                except Exception:
                    pass

    def onDelete(self, vobj, subelements):
        return True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_rigid_body(original_obj, body_type="Active", container=None):
    """
    Create an App::Link clone of *original_obj* and wrap it in a RigidBody
    feature.  The original is never modified.  Both are added to *container*
    if provided.
    """
    doc = FreeCAD.ActiveDocument

    # --- App::Link (the simulation-driven clone) ---
    link = doc.addObject("App::Link", f"Link_{original_obj.Label}")
    link.setLink(original_obj)
    link.Placement = original_obj.Placement.copy()
    link.Label = f"Link_{original_obj.Label}"

    # --- RigidBody feature ---
    rb = doc.addObject("App::FeaturePython", f"RigidBody_{original_obj.Label}")
    RigidBodyFeature(rb)
    rb.OriginalObject = original_obj
    rb.BodyLink = link
    rb.BodyType = body_type
    rb.Label = f"RigidBody_{original_obj.Label}"

    if FreeCAD.GuiUp:
        import FreeCADGui
        RigidBodyViewProvider(rb.ViewObject)

    # --- Register in container ---
    if container is not None:
        current = list(container.RigidBodies)
        current.append(rb)
        container.RigidBodies = current

    doc.recompute()
    return rb
