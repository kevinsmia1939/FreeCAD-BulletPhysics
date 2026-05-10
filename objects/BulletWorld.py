import FreeCAD


class BulletWorldFeature:
    def __init__(self, obj):
        obj.addProperty("App::PropertyFloat", "Gravity", "Physics",
                        "Gravitational acceleration magnitude (m/s²)")
        obj.Gravity = 9.81

        obj.addProperty("App::PropertyVector", "GravityDirection", "Physics",
                        "Gravity direction unit vector (default: −Z = downward)")
        obj.GravityDirection = FreeCAD.Vector(0, 0, -1)

        obj.addProperty("App::PropertyFloat", "EndTime", "Simulation",
                        "Total simulation duration in seconds. "
                        "The number of recorded frames = EndTime / TimeStep.")
        obj.EndTime = 10.0

        obj.addProperty("App::PropertyFloat", "TimeStep", "Simulation",
                        "Duration of each recorded frame in seconds (e.g. 1/60 ≈ 0.01667). "
                        "The Bullet tick = TimeStep / SubSteps, so increasing SubSteps "
                        "improves accuracy without changing playback speed or total duration.")
        obj.TimeStep = 1.0 / 60.0

        obj.addProperty("App::PropertyInteger", "SolverIterations", "Simulation",
                        "Bullet constraint-solver iterations per step")
        obj.SolverIterations = 10

        obj.addProperty("App::PropertyInteger", "SubSteps", "Simulation",
                        "Physics sub-steps per recorded frame. "
                        "Higher values prevent objects passing through each other "
                        "at the cost of simulation time (default 4)")
        obj.SubSteps = 4

        obj.addProperty("App::PropertyFloat", "MeshResolution", "Simulation",
                        "Tessellation chord deviation in mm for custom (non-primitive) "
                        "collision shapes. Smaller = finer mesh, more accurate but slower. "
                        "Primitives (box, sphere, cylinder) are unaffected.")
        obj.MeshResolution = 1.0

        obj.addProperty("App::PropertyFloat", "CollisionMargin", "Physics",
                        "Extra gap (mm) added around each mesh collision shape by Bullet's "
                        "GJK solver. The default Bullet value (40 mm) causes objects placed "
                        "touching to bounce apart at t=0. Keep this small (0.1–1 mm).")
        obj.CollisionMargin = 0.1

        obj.addProperty("App::PropertyFloat", "LinearDamping", "Physics",
                        "Air damping applied to linear (translational) velocity of active "
                        "bodies each step. 0 = no damping, 1 = full stop. "
                        "Simulates air/fluid drag on translation.")
        obj.LinearDamping = 0.0

        obj.addProperty("App::PropertyFloat", "AngularDamping", "Physics",
                        "Air damping applied to angular (rotational) velocity of active "
                        "bodies each step. 0 = no damping, 1 = full stop. "
                        "Simulates air/fluid drag on rotation.")
        obj.AngularDamping = 0.0

        obj.Proxy = self

    def _ensure_properties(self, obj):
        """Add any properties that are missing (handles objects created by older code)."""
        if not hasattr(obj, "EndTime"):
            obj.addProperty("App::PropertyFloat", "EndTime", "Simulation",
                            "Total simulation duration in seconds. "
                            "The number of recorded frames = EndTime / TimeStep.")
            # Migrate from old Steps property if present
            old_steps = getattr(obj, "Steps", 500)
            old_dt    = getattr(obj, "TimeStep", 1.0 / 60.0)
            obj.EndTime = old_steps * old_dt
        if not hasattr(obj, "SubSteps"):
            obj.addProperty("App::PropertyInteger", "SubSteps", "Simulation",
                            "Physics sub-steps per recorded frame. "
                            "Higher values prevent objects passing through each other "
                            "at the cost of simulation time (default 4)")
            obj.SubSteps = 4
        if not hasattr(obj, "MeshResolution"):
            obj.addProperty("App::PropertyFloat", "MeshResolution", "Simulation",
                            "Tessellation chord deviation in mm for custom (non-primitive) "
                            "collision shapes. Smaller = finer mesh, more accurate but slower. "
                            "Primitives (box, sphere, cylinder) are unaffected.")
            obj.MeshResolution = 1.0
        if not hasattr(obj, "CollisionMargin"):
            obj.addProperty("App::PropertyFloat", "CollisionMargin", "Physics",
                            "Extra gap (mm) added around each mesh collision shape by Bullet's "
                            "GJK solver. Keep small (0.1–1 mm) to avoid touching objects bouncing.")
            obj.CollisionMargin = 0.1
        if not hasattr(obj, "LinearDamping"):
            obj.addProperty("App::PropertyFloat", "LinearDamping", "Physics",
                            "Air damping applied to linear (translational) velocity of active "
                            "bodies each step. 0 = no damping, 1 = full stop.")
            obj.LinearDamping = 0.0
        if not hasattr(obj, "AngularDamping"):
            obj.addProperty("App::PropertyFloat", "AngularDamping", "Physics",
                            "Air damping applied to angular (rotational) velocity of active "
                            "bodies each step. 0 = no damping, 1 = full stop.")
            obj.AngularDamping = 0.0

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        self._ensure_properties(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class BulletWorldViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        import os
        import BulletUtils
        return os.path.join(BulletUtils.MOD_PATH, "icons", "BulletWorld.svg")

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def find_world(doc=None):
    """Return the first BulletWorld in the document, or None."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return None
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletWorldFeature"):
            return obj
    return None
