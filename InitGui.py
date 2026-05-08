class BulletPhysicsWorkbench(Workbench):
    MenuText = "Bullet Physics"
    ToolTip = "Bullet Physics rigid body simulation"

    def __init__(self):
        import os
        import BulletUtils
        self.__class__.Icon = os.path.join(
            BulletUtils.MOD_PATH, "icons", "BulletPhysics.svg"
        )

    def Initialize(self):
        import commands.CmdCreateContainer
        import commands.CmdAddRigidBody
        import commands.CmdRunSimulation

        tool_list = [
            "BulletPhysics_CreateContainer",
            "Separator",
            "BulletPhysics_AddActiveBody",
            "BulletPhysics_AddPassiveBody",
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
