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
    """Task panel: simulate (using BulletWorld settings) then play back."""

    def __init__(self):
        self.frames = []
        self.time_step = 1.0 / 60.0
        self._playing = False

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Bullet Physics")
        root = QtWidgets.QVBoxLayout(self.form)
        root.setSpacing(6)

        # ── Simulation section ───────────────────────────────────────────────
        sim_group = QtWidgets.QGroupBox("Simulation")
        sim_layout = QtWidgets.QVBoxLayout(sim_group)

        self._world_label = QtWidgets.QLabel()
        self._world_label.setWordWrap(True)
        sim_layout.addWidget(self._world_label)

        self.sim_btn = QtWidgets.QPushButton("Simulate")
        self.sim_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        sim_layout.addWidget(self.sim_btn)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        sim_layout.addWidget(self.progress)

        self.sim_status = QtWidgets.QLabel("Ready.")
        sim_layout.addWidget(self.sim_status)

        root.addWidget(sim_group)

        # ── Playback section ─────────────────────────────────────────────────
        play_group = QtWidgets.QGroupBox("Playback")
        play_layout = QtWidgets.QVBoxLayout(play_group)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        play_layout.addWidget(self.slider)

        self.frame_label = QtWidgets.QLabel("Frame — / —  (—)")
        self.frame_label.setAlignment(QtCore.Qt.AlignCenter)
        play_layout.addWidget(self.frame_label)

        # Transport row
        transport = QtWidgets.QHBoxLayout()
        transport.setSpacing(2)

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
        self.speed_combo.setCurrentIndex(3)
        self.speed_combo.setEnabled(False)
        opts.addWidget(self.speed_combo)
        opts.addStretch()
        self.loop_chk = QtWidgets.QCheckBox("Loop")
        self.loop_chk.setChecked(True)
        opts.addWidget(self.loop_chk)
        play_layout.addLayout(opts)

        # Reset button — always available, restores Links to original placements
        self.reset_btn = QtWidgets.QPushButton("Reset to Initial Position")
        self.reset_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_DialogResetButton))
        self.reset_btn.setToolTip(
            "Stop playback and restore all simulation objects to their\n"
            "positions before the simulation was run.")
        play_layout.addWidget(self.reset_btn)

        self.delete_cache_btn = QtWidgets.QPushButton("Delete Cache")
        self.delete_cache_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_TrashIcon))
        self.delete_cache_btn.setToolTip(
            "Delete the saved simulation cache file from disk.")
        play_layout.addWidget(self.delete_cache_btn)

        root.addWidget(play_group)
        root.addStretch()

        # ── Timer ─────────────────────────────────────────────────────────────
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._advance)

        # ── Wiring ────────────────────────────────────────────────────────────
        self.sim_btn.clicked.connect(self._run_simulation)
        self.reset_btn.clicked.connect(self._reset)
        self.delete_cache_btn.clicked.connect(self._delete_cache)
        self.slider.valueChanged.connect(self._on_slider)
        self.btn_start.clicked.connect(self._go_start)
        self.btn_back.clicked.connect(self._step_back)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_forward.clicked.connect(self._step_forward)
        self.btn_end.clicked.connect(self._go_end)
        self.speed_combo.currentIndexChanged.connect(self._update_timer_interval)

        self._refresh_world_label()
        self._try_load_cache()

    # ── World info ──────────────────────────────────────────────────────────

    def _refresh_world_label(self):
        from objects.BulletWorld import find_world
        world = find_world()
        if world:
            d = world.GravityDirection
            sub_steps = max(1, getattr(world, "SubSteps", 4))
            tick_ms = world.TimeStep / sub_steps * 1000
            self._world_label.setText(
                f"<b>Physics World:</b> {world.Label}<br>"
                f"Gravity: {world.Gravity:.2f} m/s²  "
                f"dir ({d.x:.1f}, {d.y:.1f}, {d.z:.1f})<br>"
                f"Steps: {world.Steps}  ·  "
                f"Frame: {world.TimeStep*1000:.2f} ms  ·  "
                f"SubSteps: {sub_steps}  ·  "
                f"Tick: {tick_ms:.3f} ms"
            )
        else:
            self._world_label.setText(
                "<i>No Physics World found.<br>"
                "Create a container first.</i>"
            )

    # ── Simulation ──────────────────────────────────────────────────────────

    def _run_simulation(self):
        from simulation.BulletSimulation import run_simulation
        self._stop()
        self._refresh_world_label()
        self.sim_btn.setEnabled(False)
        self.progress.setValue(0)
        self.sim_status.setText("Running…")

        def cb(done, total):
            self.progress.setValue(int(done * 100 / total))
            QtWidgets.QApplication.processEvents()

        result = run_simulation(callback=cb)
        self.sim_btn.setEnabled(True)

        if not result:
            self.sim_status.setText("Simulation failed — see Report View.")
            return

        self.frames, self.time_step = result
        from simulation.BulletSimulation import save_simulation_cache
        save_simulation_cache(self.frames, self.time_step)
        self._populate_playback(apply_first_frame=True)
        n = len(self.frames) - 1
        total_secs = n * self.time_step
        self.sim_status.setText(
            f"Done — {n} steps  ({total_secs:.2f} s simulated)")

    def _try_load_cache(self):
        from simulation.BulletSimulation import load_simulation_cache
        result = load_simulation_cache()
        if result is None:
            return
        self.frames, self.time_step = result
        self._populate_playback(apply_first_frame=False)
        n = len(self.frames) - 1
        total_secs = n * self.time_step
        self.sim_status.setText(
            f"Cache loaded — {n} steps  ({total_secs:.2f} s simulated)")

    def _populate_playback(self, apply_first_frame=False):
        """Enable all playback controls after frames are loaded."""
        if apply_first_frame:
            from simulation.BulletSimulation import apply_frame
            apply_frame(self.frames[0])
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
            ms = max(1, int(self.time_step * 1000 / self._speed_multiplier()))
            self.timer.setInterval(ms)

    def _update_frame_label(self, idx):
        if not self.frames:
            self.frame_label.setText("Frame — / —  (—)")
            return
        total = len(self.frames) - 1
        t = idx * self.time_step
        self.frame_label.setText(f"Frame {idx} / {total}  ({t:.3f} s)")

    def _on_slider(self, value):
        if self.frames:
            from simulation.BulletSimulation import apply_frame
            apply_frame(self.frames[value])
            self._update_frame_label(value)

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
        ms = max(1, int(self.time_step * 1000 / self._speed_multiplier()))
        self.timer.start(ms)

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
        self.slider.setValue(next_idx)

    def _reset(self):
        """Restore every Link to the placement it had before simulation."""
        self._stop()
        from simulation.BulletSimulation import collect_rigid_bodies
        for rb in collect_rigid_bodies():
            try:
                rb.BodyLink.Placement = rb.OriginalObject.Placement.copy()
            except Exception:
                pass
        FreeCADGui.updateGui()
        # Sync slider back to frame 0 without re-applying a recorded frame
        if self.frames:
            self.slider.blockSignals(True)
            self.slider.setValue(0)
            self.slider.blockSignals(False)
            self._update_frame_label(0)

    def _delete_cache(self):
        from simulation.BulletSimulation import delete_simulation_cache
        deleted = delete_simulation_cache()
        if deleted:
            self.frames = []
            self.time_step = 1.0 / 60.0
            self.slider.setRange(0, 0)
            self.slider.setEnabled(False)
            self.speed_combo.setEnabled(False)
            for btn in (self.btn_start, self.btn_back, self.btn_play,
                        self.btn_forward, self.btn_end):
                btn.setEnabled(False)
            self._update_frame_label(0)
            self.sim_status.setText("Cache deleted.")
        else:
            self.sim_status.setText("No cache file found.")

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
            "ToolTip": "Simulate and play back with timeline. Settings from Physics World.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Control.showDialog(SimulationPanel())


FreeCADGui.addCommand("BulletPhysics_RunSimulation", RunSimulationCommand())
