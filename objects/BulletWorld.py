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


class WorldSettingsPanel:
    """Task panel exposing all BulletWorld properties as editable fields."""

    def __init__(self, world_obj):
        try:
            from PySide2 import QtWidgets
        except ImportError:
            from PySide import QtWidgets

        self._obj = world_obj

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Physics World Settings")
        self.form.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding)

        root = QtWidgets.QVBoxLayout(self.form)

        # ── Physics ───────────────────────────────────────────────────────────
        phys_group = QtWidgets.QGroupBox("Physics")
        phys_form  = QtWidgets.QFormLayout(phys_group)

        self.inp_gravity = QtWidgets.QDoubleSpinBox()
        self.inp_gravity.setRange(0.0, 1000.0)
        self.inp_gravity.setDecimals(4)
        self.inp_gravity.setSuffix(" m/s²")
        self.inp_gravity.setToolTip("Gravitational acceleration magnitude")
        self.inp_gravity.setValue(getattr(world_obj, "Gravity", 9.81))
        phys_form.addRow("Gravity:", self.inp_gravity)

        gd = getattr(world_obj, "GravityDirection", FreeCAD.Vector(0, 0, -1))
        gdir_widget = QtWidgets.QWidget()
        gdir_layout = QtWidgets.QHBoxLayout(gdir_widget)
        gdir_layout.setContentsMargins(0, 0, 0, 0)
        self.inp_gx = QtWidgets.QDoubleSpinBox()
        self.inp_gy = QtWidgets.QDoubleSpinBox()
        self.inp_gz = QtWidgets.QDoubleSpinBox()
        for sp, label, val in ((self.inp_gx, "X", gd.x),
                               (self.inp_gy, "Y", gd.y),
                               (self.inp_gz, "Z", gd.z)):
            sp.setRange(-1.0, 1.0)
            sp.setDecimals(4)
            sp.setSingleStep(0.1)
            sp.setValue(val)
            gdir_layout.addWidget(QtWidgets.QLabel(label))
            gdir_layout.addWidget(sp)
        gdir_widget.setToolTip("Gravity direction unit vector (−Z = downward)")
        phys_form.addRow("Gravity Direction:", gdir_widget)

        self.inp_lin_damp = QtWidgets.QDoubleSpinBox()
        self.inp_lin_damp.setRange(0.0, 1.0)
        self.inp_lin_damp.setDecimals(4)
        self.inp_lin_damp.setSingleStep(0.01)
        self.inp_lin_damp.setToolTip("Linear (translational) air damping  0 = none, 1 = full stop")
        self.inp_lin_damp.setValue(getattr(world_obj, "LinearDamping", 0.0))
        phys_form.addRow("Linear Damping:", self.inp_lin_damp)

        self.inp_ang_damp = QtWidgets.QDoubleSpinBox()
        self.inp_ang_damp.setRange(0.0, 1.0)
        self.inp_ang_damp.setDecimals(4)
        self.inp_ang_damp.setSingleStep(0.01)
        self.inp_ang_damp.setToolTip("Angular (rotational) air damping  0 = none, 1 = full stop")
        self.inp_ang_damp.setValue(getattr(world_obj, "AngularDamping", 0.0))
        phys_form.addRow("Angular Damping:", self.inp_ang_damp)

        root.addWidget(phys_group)

        # ── Simulation ────────────────────────────────────────────────────────
        sim_group = QtWidgets.QGroupBox("Simulation")
        sim_form  = QtWidgets.QFormLayout(sim_group)

        self.inp_end_time = QtWidgets.QDoubleSpinBox()
        self.inp_end_time.setRange(0.001, 3600.0)
        self.inp_end_time.setDecimals(3)
        self.inp_end_time.setSuffix(" s")
        self.inp_end_time.setToolTip("Total simulation duration in seconds")
        self.inp_end_time.setValue(getattr(world_obj, "EndTime", 10.0))
        sim_form.addRow("End Time:", self.inp_end_time)

        self.inp_timestep = QtWidgets.QDoubleSpinBox()
        self.inp_timestep.setRange(0.0001, 1.0)
        self.inp_timestep.setDecimals(6)
        self.inp_timestep.setSingleStep(0.001)
        self.inp_timestep.setSuffix(" s")
        self.inp_timestep.setToolTip(
            "Duration of each recorded frame in seconds (e.g. 1/60 ≈ 0.016667).\n"
            "Frames = EndTime / TimeStep.")
        self.inp_timestep.setValue(getattr(world_obj, "TimeStep", 1.0 / 60.0))
        sim_form.addRow("Time Step:", self.inp_timestep)

        self.inp_solver = QtWidgets.QSpinBox()
        self.inp_solver.setRange(1, 1000)
        self.inp_solver.setToolTip("Bullet constraint-solver iterations per step")
        self.inp_solver.setValue(getattr(world_obj, "SolverIterations", 10))
        sim_form.addRow("Solver Iterations:", self.inp_solver)

        self.inp_substeps = QtWidgets.QSpinBox()
        self.inp_substeps.setRange(1, 100)
        self.inp_substeps.setToolTip(
            "Physics sub-steps per recorded frame.\n"
            "Higher values improve collision accuracy at the cost of simulation time.")
        self.inp_substeps.setValue(getattr(world_obj, "SubSteps", 4))
        sim_form.addRow("Sub Steps:", self.inp_substeps)

        self.inp_meshres = QtWidgets.QDoubleSpinBox()
        self.inp_meshres.setRange(0.001, 100.0)
        self.inp_meshres.setDecimals(3)
        self.inp_meshres.setSuffix(" mm")
        self.inp_meshres.setToolTip(
            "Tessellation chord deviation for custom mesh collision shapes.\n"
            "Smaller = finer mesh, more accurate but slower.\n"
            "Primitives (box, sphere, cylinder) are unaffected.")
        self.inp_meshres.setValue(getattr(world_obj, "MeshResolution", 1.0))
        sim_form.addRow("Mesh Resolution:", self.inp_meshres)

        root.addWidget(sim_group)
        root.addStretch(1)

        # ── Live-apply wiring ─────────────────────────────────────────────────
        self.inp_gravity.valueChanged.connect(self._apply)
        self.inp_gx.valueChanged.connect(self._apply)
        self.inp_gy.valueChanged.connect(self._apply)
        self.inp_gz.valueChanged.connect(self._apply)
        self.inp_lin_damp.valueChanged.connect(self._apply)
        self.inp_ang_damp.valueChanged.connect(self._apply)
        self.inp_end_time.valueChanged.connect(self._apply)
        self.inp_timestep.valueChanged.connect(self._apply)
        self.inp_solver.valueChanged.connect(self._apply)
        self.inp_substeps.valueChanged.connect(self._apply)
        self.inp_meshres.valueChanged.connect(self._apply)

    def _apply(self):
        obj = self._obj
        obj.Gravity          = self.inp_gravity.value()
        obj.GravityDirection = FreeCAD.Vector(
            self.inp_gx.value(), self.inp_gy.value(), self.inp_gz.value())
        obj.LinearDamping    = self.inp_lin_damp.value()
        obj.AngularDamping   = self.inp_ang_damp.value()
        obj.EndTime          = self.inp_end_time.value()
        obj.TimeStep         = self.inp_timestep.value()
        obj.SolverIterations = self.inp_solver.value()
        obj.SubSteps         = self.inp_substeps.value()
        obj.MeshResolution   = self.inp_meshres.value()

    def reject(self):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()


class BulletWorldViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        import os
        import BulletUtils
        return os.path.join(BulletUtils.MOD_PATH, "icons", "BulletWorld.svg")

    def setEdit(self, vobj, mode):
        import FreeCADGui
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Control.showDialog(WorldSettingsPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        self.setEdit(vobj, 0)
        return True

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
