import FreeCAD


class BulletWorldFeature:
    def __init__(self, obj):
        obj.addProperty("App::PropertyFloat", "Gravity", "Physics",
                        "Gravitational acceleration magnitude (m/s²)")
        obj.Gravity = 9.81

        obj.addProperty("App::PropertyVector", "GravityDirection", "Physics",
                        "Gravity direction unit vector (default: −Z = downward)")
        obj.GravityDirection = FreeCAD.Vector(0, 0, -1)

        obj.addProperty("App::PropertyFloat", "TimeStep", "Simulation",
                        "Physics time step in seconds (e.g. 1/60 ≈ 0.01667)")
        obj.TimeStep = 1.0 / 60.0

        obj.addProperty("App::PropertyInteger", "Steps", "Simulation",
                        "Total number of simulation steps to record")
        obj.Steps = 500

        obj.addProperty("App::PropertyInteger", "SolverIterations", "Simulation",
                        "Bullet constraint-solver iterations per step")
        obj.SolverIterations = 10

        obj.Proxy = self

    def execute(self, obj):
        pass

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
