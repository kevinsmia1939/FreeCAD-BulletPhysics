import os
import FreeCAD
import FreeCADGui

MOD_PATH = os.path.dirname(os.path.dirname(__file__))


class SimulationDialog:
    """Task panel shown in the panel area while the simulation runs."""

    def __init__(self):
        try:
            from PySide2 import QtWidgets, QtCore
        except ImportError:
            from PySide import QtWidgets, QtCore

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Bullet Physics Simulation")

        layout = QtWidgets.QVBoxLayout(self.form)

        # --- settings ---
        grid = QtWidgets.QFormLayout()
        layout.addLayout(grid)

        self.steps_spin = QtWidgets.QSpinBox()
        self.steps_spin.setRange(10, 10000)
        self.steps_spin.setValue(500)
        self.steps_spin.setSuffix(" steps")
        grid.addRow("Simulation steps:", self.steps_spin)

        self.fps_spin = QtWidgets.QDoubleSpinBox()
        self.fps_spin.setRange(1.0, 240.0)
        self.fps_spin.setValue(60.0)
        self.fps_spin.setSuffix(" Hz")
        grid.addRow("Time step rate:", self.fps_spin)

        # --- run button ---
        self.run_btn = QtWidgets.QPushButton("Run Simulation")
        self.run_btn.setIcon(
            QtWidgets.QApplication.style().standardIcon(
                QtWidgets.QStyle.SP_MediaPlay))
        layout.addWidget(self.run_btn)

        # --- progress ---
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QtWidgets.QLabel("Ready.")
        layout.addWidget(self.status_label)

        layout.addStretch()

        self.run_btn.clicked.connect(self._run)

    def _run(self):
        from simulation.BulletSimulation import run_simulation

        steps = self.steps_spin.value()
        hz = self.fps_spin.value()
        self.progress.setValue(0)
        self.status_label.setText("Running…")
        self.run_btn.setEnabled(False)

        def progress_cb(done, total):
            pct = int(done * 100 / total)
            self.progress.setValue(pct)

        try:
            ok = run_simulation(steps=steps, time_step=1.0 / hz,
                                callback=progress_cb)
            if ok:
                self.status_label.setText(f"Done — {steps} steps simulated.")
            else:
                self.status_label.setText("Simulation did not run (check report view).")
        except Exception as exc:
            self.status_label.setText(f"Error: {exc}")
            FreeCAD.Console.PrintError(f"BulletPhysics simulation error: {exc}\n")
        finally:
            self.run_btn.setEnabled(True)

    def reject(self):
        FreeCADGui.Control.closeDialog()


class RunSimulationCommand:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(MOD_PATH, "icons", "RunSimulation.svg"),
            "MenuText": "Run Simulation",
            "ToolTip": "Open the simulation panel and run Bullet Physics.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        panel = SimulationDialog()
        FreeCADGui.Control.showDialog(panel)


FreeCADGui.addCommand("BulletPhysics_RunSimulation", RunSimulationCommand())
