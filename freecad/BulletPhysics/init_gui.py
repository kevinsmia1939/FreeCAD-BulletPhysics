import FreeCADGui


class BulletPhysicsWorkbench(FreeCADGui.Workbench):
    MenuText = "Bullet Physics"
    ToolTip = "Bullet Physics rigid body simulation"

    def __init__(self):
        import os
        from . import BulletUtils
        self.__class__.Icon = os.path.join(BulletUtils.ICONS_PATH, "BulletPhysics.svg")
        FreeCADGui.addIconPath(BulletUtils.ICONS_PATH)
        from .preferences.BulletPreferences import BulletPreferencesPage
        FreeCADGui.addPreferencePage(BulletPreferencesPage, "Bullet Physics")

    def Initialize(self):
        from .commands import CmdCreateContainer
        from .commands import CmdAddRigidBody
        from .commands import CmdAddLauncher
        from .commands import CmdDowngrade
        from .commands import CmdRunSimulation

        tool_list = [
            "BulletPhysics_CreateContainer",
            "Separator",
            "BulletPhysics_AddActiveBody",
            "BulletPhysics_AddPassiveBody",
            "Separator",
            "BulletPhysics_Downgrade",
            "Separator",
            "BulletPhysics_AddLauncher",
            "Separator",
            "BulletPhysics_RunSimulation",
        ]
        self.appendToolbar("Bullet Physics", tool_list)
        self.appendMenu("&Bullet Physics", tool_list)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(BulletPhysicsWorkbench())
