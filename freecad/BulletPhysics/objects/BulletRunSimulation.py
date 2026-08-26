import os

import FreeCAD


class RunSimulationFeature:
    """Tree object that opens the simulation and playback task panel."""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        if FreeCAD.GuiUp:
            obj.ViewObject.Visibility = True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class RunSimulationViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        from .. import BulletUtils
        return os.path.join(BulletUtils.ICONS_PATH, "RunSimulation.svg")

    def setEdit(self, vobj, mode):
        import FreeCADGui
        from ..commands.CmdRunSimulation import SimulationPanel
        FreeCADGui.Control.showDialog(SimulationPanel())
        return True

    def unsetEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        return self.setEdit(vobj, 0)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_run_simulation(container):
    doc = container.Document
    # This task object deliberately has no geometry, but Part::FeaturePython
    # keeps its icon active in FreeCAD's tree like the CfdOF solver objects.
    simulation = doc.addObject("Part::FeaturePython", "RunSimulation")
    RunSimulationFeature(simulation)
    simulation.Label = "Run Simulation"
    if FreeCAD.GuiUp:
        RunSimulationViewProvider(simulation.ViewObject)
        # This task object has no geometry but must remain active in the tree.
        simulation.ViewObject.Visibility = True
    container.RunSimulation = simulation
    return simulation
