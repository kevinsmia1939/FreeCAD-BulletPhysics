import FreeCAD


class BulletLauncherFeature:
    """
    Keeps the target active rigid body frozen (static) until LaunchTime,
    then releases it with an instantaneous velocity impulse.
    """

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "TargetBody", "Launcher",
                        "The active rigid body to hold and then launch")

        obj.addProperty("App::PropertyFloat", "LaunchTime", "Launcher",
                        "Simulation time in seconds at which the body is released "
                        "and the velocity impulse is applied")
        obj.LaunchTime = 2.0

        obj.addProperty("App::PropertyFloat", "Velocity", "Launcher",
                        "Launch speed in m/s applied at LaunchTime")
        obj.Velocity = 10.0

        obj.addProperty("App::PropertyVector", "Direction", "Launcher",
                        "Launch direction (normalised automatically). "
                        "Default (0, 0, 1) = straight up.")
        obj.Direction = FreeCAD.Vector(0, 0, 1)

        obj.Proxy = self

    def execute(self, obj):
        pass

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class BulletLauncherViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        import os
        import BulletUtils
        return os.path.join(BulletUtils.MOD_PATH, "icons", "BulletLauncher.svg")

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_launcher(target_rb, container=None):
    doc = FreeCAD.ActiveDocument
    name = f"Launcher_{target_rb.Label}"
    obj = doc.addObject("App::FeaturePython", name)
    BulletLauncherFeature(obj)
    obj.TargetBody = target_rb
    obj.Label = name

    if FreeCAD.GuiUp:
        import FreeCADGui
        BulletLauncherViewProvider(obj.ViewObject)

    if container is not None:
        current = list(getattr(container, "Launchers", []))
        current.append(obj)
        container.Launchers = current

    doc.recompute()
    return obj
