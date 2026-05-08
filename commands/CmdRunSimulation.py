import os
import FreeCAD
import FreeCADGui

try:
    from PySide2 import QtCore, QtWidgets
except ImportError:
    from PySide import QtCore, QtWidgets


def _mod_path():
    import BulletUtils
    return BulletUtils.MOD_PATH


# ---------------------------------------------------------------------------
# Playback panel
# ---------------------------------------------------------------------------

class SimulationPanel:
    """FreeCAD task panel: simulate then play back with a timeline scrubber."""

    def __init__(self):
        self.frames = []        # list of frame dicts
        self.time_step = 1.0 / 60.0
        self._playing = False

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Bullet Physics")
        root = QtWidgets.QVBoxLayout(self.form)
        root.setSpacing(6)

        # ── Simulate section ────────────────────────────────────────────────
        sim_group = QtWidgets.QGroupBox("Simulation")
        sim_layout = QtWidgets.QFormLayout(sim_group)

        self.steps_spin = QtWidgets.QSpinBox()
        self.steps_spin.setRange(10, 50000)
        self.steps_spin.setValue(500)
        self.steps_spin.setSuffix(" steps")
        sim_layout.addRow("Steps:", self.steps_spin)

        self.hz_spin = QtWidgets.QDoubleSpinBox()
        self.hz_spin.setRange(1.0, 240.0)
        self.hz_spin.setValue(60.0)
        self.hz_spin.setSuffix(" Hz")
        sim_layout.addRow("Step rate:", self.hz_spin)

        self.sim_btn = QtWidgets.QPushButton("Simulate")
        self.sim_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        sim_layout.addRow(self.sim_btn)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        sim_layout.addRow(self.progress)

        self.sim_status = QtWidgets.QLabel("Ready.")
        sim_layout.addRow(self.sim_status)

        root.addWidget(sim_group)

        # ── Playback section ─────────────────────────────────────────────────
        play_group = QtWidgets.QGroupBox("Playback")
        play_layout = QtWidgets.QVBoxLayout(play_group)

        # Timeline slider
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.slider.setTickInterval(1)
        play_layout.addWidget(self.slider)

        # Frame label
        self.frame_label = QtWidgets.QLabel("Frame — / —  (—)")
        self.frame_label.setAlignment(QtCore.Qt.AlignCenter)
        play_layout.addWidget(self.frame_label)

        # Transport buttons
        transport = QtWidgets.QHBoxLayout()
        transport.setSpacing(4)

        def _tb(icon_name, tip):
            btn = QtWidgets.QToolButton()
            btn.setIcon(self.form.style().standardIcon(icon_name))
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            transport.addWidget(btn)
            return btn

        self.btn_start   = _tb(QtWidgets.QStyle.SP_MediaSkipBackward,  "First frame")
        self.btn_back    = _tb(QtWidgets.QStyle.SP_MediaSeekBackward,   "Step back")
        self.btn_play    = _tb(QtWidgets.QStyle.SP_MediaPlay,           "Play / Pause")
        self.btn_forward = _tb(QtWidgets.QStyle.SP_MediaSeekForward,    "Step forward")
        self.btn_end     = _tb(QtWidgets.QStyle.SP_MediaSkipForward,    "Last frame")

        for btn in (self.btn_start, self.btn_back, self.btn_play,
                    self.btn_forward, self.btn_end):
            btn.setEnabled(False)

        play_layout.addLayout(transport)

        # Speed + loop row
        opts = QtWidgets.QHBoxLayout()
        opts.addWidget(QtWidgets.QLabel("Speed:"))
        self.speed_combo = QtWidgets.QComboBox()
        for label in ("0.1×", "0.25×", "0.5×", "1×", "2×", "4×", "8×"):
            self.speed_combo.addItem(label)
        self.speed_combo.setCurrentIndex(3)   # 1×
        self.speed_combo.setEnabled(False)
        opts.addWidget(self.speed_combo)
        opts.addStretch()
        self.loop_chk = QtWidgets.QCheckBox("Loop")
        self.loop_chk.setChecked(True)
        opts.addWidget(self.loop_chk)
        play_layout.addLayout(opts)

        root.addWidget(play_group)
        root.addStretch()

        # ── Timer ─────────────────────────────────────────────────────────────
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._advance)

        # ── Wiring ────────────────────────────────────────────────────────────
        self.sim_btn.clicked.connect(self._run_simulation)
        self.slider.valueChanged.connect(self._on_slider)
        self.btn_start.clicked.connect(self._go_start)
        self.btn_back.clicked.connect(self._step_back)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_forward.clicked.connect(self._step_forward)
        self.btn_end.clicked.connect(self._go_end)
        self.speed_combo.currentIndexChanged.connect(self._update_timer_interval)

    # ── Simulation ──────────────────────────────────────────────────────────

    def _run_simulation(self):
        from simulation.BulletSimulation import run_simulation, apply_frame
        self._stop()
        self.sim_btn.setEnabled(False)
        self.progress.setValue(0)
        self.sim_status.setText("Running…")

        steps = self.steps_spin.value()
        self.time_step = 1.0 / self.hz_spin.value()

        def cb(done, total):
            self.progress.setValue(int(done * 100 / total))
            QtWidgets.QApplication.processEvents()

        frames = run_simulation(steps=steps, time_step=self.time_step, callback=cb)

        self.sim_btn.setEnabled(True)

        if not frames:
            self.sim_status.setText("Simulation failed — see Report View.")
            return

        self.frames = frames
        n = len(self.frames) - 1  # excludes frame 0 (initial)
        total_secs = n * self.time_step
        self.sim_status.setText(
            f"Done — {n} steps  ({total_secs:.2f} s simulated)")

        # Re-apply frame 0 (initial positions)
        apply_frame(self.frames[0])

        # Enable playback controls
        self.slider.setRange(0, len(self.frames) - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.speed_combo.setEnabled(True)
        for btn in (self.btn_start, self.btn_back, self.btn_play,
                    self.btn_forward, self.btn_end):
            btn.setEnabled(True)
        self._update_frame_label(0)

    # ── Playback helpers ────────────────────────────────────────────────────

    def _speed_multiplier(self):
        mapping = {"0.1×": 0.1, "0.25×": 0.25, "0.5×": 0.5,
                   "1×": 1.0, "2×": 2.0, "4×": 4.0, "8×": 8.0}
        return mapping.get(self.speed_combo.currentText(), 1.0)

    def _update_timer_interval(self):
        if self._playing:
            interval_ms = max(1, int(self.time_step * 1000 / self._speed_multiplier()))
            self.timer.setInterval(interval_ms)

    def _update_frame_label(self, idx):
        if not self.frames:
            self.frame_label.setText("Frame — / —  (—)")
            return
        total = len(self.frames) - 1
        t = idx * self.time_step
        self.frame_label.setText(f"Frame {idx} / {total}  ({t:.3f} s)")

    def _apply_current(self, idx):
        from simulation.BulletSimulation import apply_frame
        apply_frame(self.frames[idx])
        self._update_frame_label(idx)

    def _on_slider(self, value):
        if self.frames:
            self._apply_current(value)

    def _go_start(self):
        self._stop()
        self.slider.setValue(0)

    def _go_end(self):
        self._stop()
        self.slider.setValue(len(self.frames) - 1)

    def _step_back(self):
        self._stop()
        self.slider.setValue(max(0, self.slider.value() - 1))

    def _step_forward(self):
        self._stop()
        self.slider.setValue(min(len(self.frames) - 1, self.slider.value() + 1))

    def _toggle_play(self):
        if self._playing:
            self._stop()
        else:
            self._start_play()

    def _start_play(self):
        self._playing = True
        self.btn_play.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        interval_ms = max(1, int(self.time_step * 1000 / self._speed_multiplier()))
        self.timer.start(interval_ms)

    def _stop(self):
        self._playing = False
        self.timer.stop()
        self.btn_play.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))

    def _advance(self):
        next_idx = self.slider.value() + 1
        if next_idx >= len(self.frames):
            if self.loop_chk.isChecked():
                next_idx = 0
            else:
                self._stop()
                return
        self.slider.setValue(next_idx)   # triggers _on_slider → apply_frame

    # ── FreeCAD task panel protocol ─────────────────────────────────────────

    def reject(self):
        self._stop()
        FreeCADGui.Control.closeDialog()


# ---------------------------------------------------------------------------
# FreeCAD command
# ---------------------------------------------------------------------------

class RunSimulationCommand:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(_mod_path(), "icons", "RunSimulation.svg"),
            "MenuText": "Run Simulation",
            "ToolTip": "Simulate and play back Bullet Physics with a timeline.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Control.showDialog(SimulationPanel())


FreeCADGui.addCommand("BulletPhysics_RunSimulation", RunSimulationCommand())
