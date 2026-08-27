import os
import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets


def _mod_path():
    from .. import BulletUtils
    return BulletUtils.MOD_PATH


def _icons_path():
    from .. import BulletUtils
    return BulletUtils.ICONS_PATH


# ---------------------------------------------------------------------------
# Playback panel
# ---------------------------------------------------------------------------

class SimulationPanel:
    """Task panel: simulate (using BulletWorld settings) then play back."""

    def __init__(self):
        self.frames = []
        self.speed_frames = []
        self.time_step = 1.0 / 60.0
        self._playing = False
        self._wireframe_infos = []
        self._mesh_infos = []
        self._sim_stop_requested = False
        self._sim_paused = False
        self._closed = False
        self._loading_stop_condition = False
        self._loading_panel_settings = False

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

        sim_btn_row = QtWidgets.QHBoxLayout()
        self.sim_btn = QtWidgets.QPushButton("Simulate")
        self.sim_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        sim_btn_row.addWidget(self.sim_btn)

        self.pause_sim_btn = QtWidgets.QPushButton("Pause")
        self.pause_sim_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        self.pause_sim_btn.setToolTip(
            "Pause Bullet stepping and use playback up to the latest recorded frame.")
        self.pause_sim_btn.setEnabled(False)
        sim_btn_row.addWidget(self.pause_sim_btn)

        self.stop_sim_btn = QtWidgets.QPushButton("Stop")
        self.stop_sim_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaStop))
        self.stop_sim_btn.setToolTip("Stop the running simulation and keep frames recorded so far.")
        self.stop_sim_btn.setEnabled(False)
        sim_btn_row.addWidget(self.stop_sim_btn)
        sim_layout.addLayout(sim_btn_row)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        sim_layout.addWidget(self.progress)

        self.sim_status = QtWidgets.QLabel("Ready.")
        sim_layout.addWidget(self.sim_status)

        stop_group = QtWidgets.QGroupBox("Conditional Stop")
        stop_layout = QtWidgets.QVBoxLayout(stop_group)
        self.stop_on_contact_check = QtWidgets.QCheckBox(
            "Enable conditional stop")
        self.stop_on_contact_check.setToolTip(
            "Stop when a matching rigid body touches a shape or is inside an observer.")
        self.stop_type_combo = QtWidgets.QComboBox()
        self.stop_type_combo.addItems(["Collision Object", "Observer"])
        self.stop_target_combo = QtWidgets.QComboBox()
        self._populate_stop_targets()
        self.stop_body_type_combo = QtWidgets.QComboBox()
        self.stop_body_type_combo.addItems(["Active", "Passive", "Any"])
        self.stop_delay_spin = QtWidgets.QDoubleSpinBox()
        self.stop_delay_spin.setRange(0.0, 3600.0)
        self.stop_delay_spin.setDecimals(3)
        self.stop_delay_spin.setSingleStep(0.1)
        self.stop_delay_spin.setSuffix(" s")
        self.stop_delay_spin.setToolTip(
            "Continue simulating for this duration after the first target contact. "
            "0 stops immediately.")
        stop_layout.addWidget(self.stop_on_contact_check)
        trigger_group = QtWidgets.QGroupBox("Trigger")
        trigger_form = QtWidgets.QFormLayout(trigger_group)
        trigger_form.addRow("Source:", self.stop_type_combo)
        trigger_form.addRow("Target:", self.stop_target_combo)
        self.stop_body_type_label = QtWidgets.QLabel("Matching body type:")
        trigger_form.addRow(self.stop_body_type_label, self.stop_body_type_combo)
        stop_layout.addWidget(trigger_group)
        response_group = QtWidgets.QGroupBox("Response")
        response_form = QtWidgets.QFormLayout(response_group)
        response_form.addRow("Delay after trigger:", self.stop_delay_spin)
        stop_layout.addWidget(response_group)
        sim_layout.addWidget(stop_group)

        collision_row = QtWidgets.QHBoxLayout()
        self.collision_chk = QtWidgets.QCheckBox("Show Collision Shapes")
        self.collision_chk.setToolTip(
            "Display green wireframe outlines of each rigid body's collision\n"
            "envelope.  The wireframes animate in sync with playback.\n"
            "Available before running the simulation.")
        collision_row.addWidget(self.collision_chk)
        self.refresh_collision_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_collision_btn.setToolTip(
            "Rebuild collision wireframes from the current solid positions.\n"
            "Use this after moving or rotating a solid.")
        self.refresh_collision_btn.setEnabled(False)
        collision_row.addWidget(self.refresh_collision_btn)
        sim_layout.addLayout(collision_row)

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

        self.bake_btn = QtWidgets.QPushButton("Bake Frame as New Origin")
        self.bake_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_DialogSaveButton))
        self.bake_btn.setToolTip(
            "Copy the current frame's positions and orientations to the original\n"
            "objects, making this the new starting point for future simulations\n"
            "and CAD work.\n\n"
            "Fully undoable with Ctrl+Z. Clears the simulation cache.")
        self.bake_btn.setEnabled(False)
        play_layout.addWidget(self.bake_btn)

        root.addWidget(play_group)

        analysis_group = QtWidgets.QGroupBox("Analysis")
        analysis_layout = QtWidgets.QHBoxLayout(analysis_group)
        analysis_layout.addWidget(QtWidgets.QLabel("Speed horizontal axis:"))
        self.speed_graph_axis = QtWidgets.QComboBox()
        self.speed_graph_axis.addItems(["Time", "Frame"])
        analysis_layout.addWidget(self.speed_graph_axis)
        self.speed_graph_btn = QtWidgets.QPushButton("Show Speed Graph")
        self.speed_graph_btn.setToolTip(
            "Open a separate graph of scalar particle speed for every simulated body.")
        analysis_layout.addWidget(self.speed_graph_btn)
        root.addWidget(analysis_group)
        root.addStretch()

        # ── Timer ─────────────────────────────────────────────────────────────
        # Parent to self.form so Qt stops and destroys it when the form closes.
        self.timer = QtCore.QTimer(self.form)
        self.timer.timeout.connect(self._advance)

        # ── Wiring ────────────────────────────────────────────────────────────
        self.sim_btn.clicked.connect(self._run_simulation)
        self.stop_sim_btn.clicked.connect(self._stop_simulation)
        self.pause_sim_btn.clicked.connect(self._toggle_simulation_pause)
        self.reset_btn.clicked.connect(self._reset)
        self.delete_cache_btn.clicked.connect(self._delete_cache)
        self.bake_btn.clicked.connect(self._bake_frame)
        self.speed_graph_btn.clicked.connect(self._show_speed_graph)
        self.slider.valueChanged.connect(self._on_slider)
        self.btn_start.clicked.connect(self._go_start)
        self.btn_back.clicked.connect(self._step_back)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_forward.clicked.connect(self._step_forward)
        self.btn_end.clicked.connect(self._go_end)
        self.speed_combo.currentIndexChanged.connect(self._update_timer_interval)

        self.collision_chk.stateChanged.connect(self._on_collision_chk)
        self.collision_chk.stateChanged.connect(self._save_panel_settings)
        self.refresh_collision_btn.clicked.connect(self._rebuild_wireframes)
        self.stop_on_contact_check.toggled.connect(self._update_stop_target_state)
        self.stop_on_contact_check.toggled.connect(self._save_stop_condition)
        self.stop_target_combo.currentIndexChanged.connect(self._save_stop_condition)
        self.stop_type_combo.currentIndexChanged.connect(self._save_stop_condition)
        self.stop_type_combo.currentIndexChanged.connect(self._update_stop_target_state)
        self.stop_body_type_combo.currentIndexChanged.connect(self._save_stop_condition)
        self.stop_delay_spin.valueChanged.connect(self._save_stop_condition)
        self.speed_combo.currentIndexChanged.connect(self._save_panel_settings)
        self.loop_chk.toggled.connect(self._save_panel_settings)
        self.speed_graph_axis.currentIndexChanged.connect(self._save_panel_settings)
        self._load_stop_condition()
        self._update_stop_target_state()

        self._refresh_world_label()
        from ..simulation.BulletSimulation import (
            cleanup_stale_wireframes, cleanup_stale_mesh_displays)
        cleanup_stale_wireframes()
        cleanup_stale_mesh_displays()
        self._load_panel_settings()
        self._try_load_cache()
        if self._show_collision_mesh():
            self._rebuild_mesh_displays()

    def _populate_stop_targets(self):
        self.stop_target_combo.clear()
        self.stop_target_combo.addItem("(select an object)", None)
        for obj in FreeCAD.ActiveDocument.Objects:
            if hasattr(obj, "Shape") and obj.Shape is not None:
                self.stop_target_combo.addItem(obj.Label, obj)
            elif (hasattr(obj, "Proxy")
                  and type(obj.Proxy).__name__ == "BulletObserverFeature"):
                self.stop_target_combo.addItem(obj.Label, obj)

    def _update_stop_target_state(self):
        enabled = self.stop_on_contact_check.isChecked()
        self.stop_type_combo.setEnabled(enabled)
        self.stop_target_combo.setEnabled(enabled)
        self.stop_body_type_combo.setEnabled(enabled)
        show_body_type = self.stop_type_combo.currentText() == "Collision Object"
        self.stop_body_type_label.setVisible(show_body_type)
        self.stop_body_type_combo.setVisible(show_body_type)
        self.stop_delay_spin.setEnabled(enabled)

    def _stop_target(self):
        if not self.stop_on_contact_check.isChecked():
            return None
        return self.stop_target_combo.currentData()

    def _stop_delay(self):
        if not self.stop_on_contact_check.isChecked():
            return 0.0
        return self.stop_delay_spin.value()

    def _conditional_stop_world(self):
        from ..objects.BulletWorld import find_world

        world = find_world()
        if world is not None and hasattr(world.Proxy, "_ensure_properties"):
            world.Proxy._ensure_properties(world)
        return world

    def _load_stop_condition(self):
        world = self._conditional_stop_world()
        if world is None:
            return
        target = getattr(world, "ConditionalStopTarget", None)
        self._loading_stop_condition = True
        self.stop_on_contact_check.setChecked(
            getattr(world, "ConditionalStopEnabled", False))
        self.stop_delay_spin.setValue(max(
            0.0, getattr(world, "ConditionalStopDelay", 0.0)))
        self.stop_type_combo.setCurrentText(
            getattr(world, "ConditionalStopType", "Collision Object"))
        self.stop_body_type_combo.setCurrentText(
            getattr(world, "ConditionalStopBodyType", "Active"))
        for index in range(self.stop_target_combo.count()):
            if self.stop_target_combo.itemData(index) == target:
                self.stop_target_combo.setCurrentIndex(index)
                break
        self._loading_stop_condition = False

    def _save_stop_condition(self, *_args):
        if self._loading_stop_condition:
            return
        world = self._conditional_stop_world()
        if world is None:
            return
        world.ConditionalStopEnabled = self.stop_on_contact_check.isChecked()
        world.ConditionalStopTarget = self._stop_target()
        world.ConditionalStopType = self.stop_type_combo.currentText()
        world.ConditionalStopBodyType = self.stop_body_type_combo.currentText()
        world.ConditionalStopDelay = self.stop_delay_spin.value()
        world.Document.recompute()

    def _load_panel_settings(self):
        world = self._conditional_stop_world()
        if world is None:
            return
        self._loading_panel_settings = True
        self.collision_chk.setChecked(
            getattr(world, "ShowCollisionWireframes", False))
        speed = getattr(world, "PlaybackSpeed", "1×")
        speed_index = self.speed_combo.findText(speed)
        if speed_index >= 0:
            self.speed_combo.setCurrentIndex(speed_index)
        self.loop_chk.setChecked(getattr(world, "PlaybackLoop", True))
        axis = getattr(world, "SpeedGraphAxis", "Time")
        axis_index = self.speed_graph_axis.findText(axis)
        if axis_index >= 0:
            self.speed_graph_axis.setCurrentIndex(axis_index)
        self._loading_panel_settings = False

    def _save_panel_settings(self, *_args):
        if self._loading_panel_settings:
            return
        world = self._conditional_stop_world()
        if world is None:
            return
        world.ShowCollisionWireframes = self.collision_chk.isChecked()
        world.PlaybackSpeed = self.speed_combo.currentText()
        world.PlaybackLoop = self.loop_chk.isChecked()
        world.SpeedGraphAxis = self.speed_graph_axis.currentText()
        world.Document.recompute()

    # ── World info ──────────────────────────────────────────────────────────

    def _refresh_world_label(self):
        from ..objects.BulletWorld import find_world
        world = find_world()
        if world:
            d = world.GravityDirection
            sub_steps = max(1, getattr(world, "SubSteps", 4))
            end_time  = getattr(world, "EndTime", 10.0)
            tick_ms   = world.TimeStep / sub_steps * 1000
            self._world_label.setText(
                f"<b>Physics World:</b> {world.Label}<br>"
                f"Gravity: {world.Gravity:.2f} m/s²  "
                f"dir ({d.x:.1f}, {d.y:.1f}, {d.z:.1f})<br>"
                f"End time: {end_time:.2f} s  ·  "
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
        from ..simulation.BulletSimulation import (
            get_last_stop_reason, run_simulation)
        self._stop()
        self._refresh_world_label()
        self._sim_stop_requested = False
        self._sim_paused = False
        self.sim_btn.setEnabled(False)
        self.stop_sim_btn.setEnabled(True)
        self.pause_sim_btn.setEnabled(True)
        self.pause_sim_btn.setText("Pause")
        self.pause_sim_btn.setIcon(
            self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        for button in (self.reset_btn, self.delete_cache_btn, self.bake_btn):
            button.setEnabled(False)
        self.progress.setValue(0)
        self.sim_status.setText("Running…")

        def cb(done, total, frames, speed_frames, time_step):
            self._update_live_frames(frames, speed_frames, time_step)
            self.progress.setValue(int(done * 100 / total))
            QtWidgets.QApplication.processEvents()
            while (self._sim_paused and not self._sim_stop_requested
                   and not self._closed):
                QtWidgets.QApplication.processEvents()
                QtCore.QThread.msleep(15)
            if self._sim_stop_requested or self._closed:
                return False  # signal run_simulation to break early

        result = run_simulation(
            callback=cb,
            stop_on_contact=self._stop_target(),
            stop_delay=self._stop_delay(),
            stop_body_type=self.stop_body_type_combo.currentText())
        self.sim_btn.setEnabled(True)
        self.stop_sim_btn.setEnabled(False)
        self.pause_sim_btn.setEnabled(False)
        self._sim_paused = False

        if not result:
            self.reset_btn.setEnabled(True)
            self.delete_cache_btn.setEnabled(True)
            self.bake_btn.setEnabled(bool(self.frames))
            self.sim_status.setText("Simulation failed — see Report View.")
            return

        self.frames, self.time_step, self.speed_frames = result
        from ..simulation.BulletSimulation import save_simulation_cache
        save_simulation_cache(self.frames, self.time_step, self.speed_frames)
        self._populate_playback(apply_first_frame=True)
        if self.collision_chk.isChecked():
            self._rebuild_wireframes()
        if self._show_collision_mesh():
            self._rebuild_mesh_displays()
        n = len(self.frames) - 1
        total_secs = n * self.time_step
        stop_reason = get_last_stop_reason()
        if stop_reason:
            stopped = f" (stopped: {stop_reason})"
        elif self._sim_stop_requested:
            stopped = " (stopped early)"
        else:
            stopped = ""
        self.sim_status.setText(
            f"Done — {n} frames  ({total_secs:.2f} s simulated){stopped}")

    def _stop_simulation(self):
        self._sim_stop_requested = True
        self._sim_paused = False
        self.stop_sim_btn.setEnabled(False)
        self.pause_sim_btn.setEnabled(False)
        self.sim_status.setText("Stopping…")

    def _toggle_simulation_pause(self):
        self._sim_paused = not self._sim_paused
        if self._sim_paused:
            self._stop()
            self.pause_sim_btn.setText("Continue")
            self.pause_sim_btn.setIcon(
                self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
            self._enable_live_playback()
            last = len(self.frames) - 1
            if last >= 0:
                self.slider.setValue(last)
                self._on_slider(last)
            self.sim_status.setText(
                f"Paused at frame {max(0, last)}. Use playback, then press Continue.")
        else:
            self._stop()
            self.pause_sim_btn.setText("Pause")
            self.pause_sim_btn.setIcon(
                self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
            self._disable_live_playback()
            self.sim_status.setText("Running…")

    def _update_live_frames(self, frames, speed_frames, time_step):
        """Expose recorded frames to the slider without altering live Bullet state."""
        self.frames = frames
        self.speed_frames = speed_frames
        self.time_step = time_step
        last = len(frames) - 1
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, last))
        self.slider.setValue(max(0, last))
        self.slider.blockSignals(False)
        self._update_frame_label(max(0, last))

    def _enable_live_playback(self):
        self.slider.setEnabled(bool(self.frames))
        self.speed_combo.setEnabled(bool(self.frames))
        for button in (self.btn_start, self.btn_back, self.btn_play,
                       self.btn_forward, self.btn_end):
            button.setEnabled(bool(self.frames))

    def _disable_live_playback(self):
        self._stop()
        self.slider.setEnabled(False)
        self.speed_combo.setEnabled(False)
        for button in (self.btn_start, self.btn_back, self.btn_play,
                       self.btn_forward, self.btn_end):
            button.setEnabled(False)

    def _try_load_cache(self):
        from ..simulation.BulletSimulation import load_simulation_cache
        result = load_simulation_cache()
        if result is None:
            return
        self.frames, self.time_step, self.speed_frames = result
        self._populate_playback(apply_first_frame=False)
        n = len(self.frames) - 1
        total_secs = n * self.time_step
        self.sim_status.setText(
            f"Cache loaded — {n} steps  ({total_secs:.2f} s simulated)")

    def _populate_playback(self, apply_first_frame=False):
        """Enable all playback controls after frames are loaded."""
        if apply_first_frame:
            from ..simulation.BulletSimulation import apply_frame
            apply_frame(self.frames[0])
        self.slider.setRange(0, len(self.frames) - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.speed_combo.setEnabled(True)
        for btn in (self.btn_start, self.btn_back, self.btn_play,
                    self.btn_forward, self.btn_end):
            btn.setEnabled(True)
        self.bake_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        self.delete_cache_btn.setEnabled(True)
        self._update_frame_label(0)

    # ── Playback helpers ────────────────────────────────────────────────────

    def _speed_multiplier(self):
        mapping = {"0.1×": 0.1, "0.25×": 0.25, "0.5×": 0.5,
                   "1×": 1.0, "2×": 2.0, "4×": 4.0, "8×": 8.0}
        return mapping.get(self.speed_combo.currentText(), 1.0)

    def _update_timer_interval(self):
        if self._closed or not self._playing:
            return
        try:
            ms = max(1, int(self.time_step * 1000 / self._speed_multiplier()))
            self.timer.setInterval(ms)
        except RuntimeError:
            self.timer.stop()

    def _update_frame_label(self, idx):
        if self._closed:
            return
        try:
            if not self.frames:
                self.frame_label.setText("Frame — / —  (—)")
                return
            total = len(self.frames) - 1
            t = idx * self.time_step
            self.frame_label.setText(f"Frame {idx} / {total}  ({t:.3f} s)")
        except RuntimeError:
            pass

    def _on_slider(self, value):
        if self._closed:
            return
        try:
            if self.frames:
                from ..simulation.BulletSimulation import (
                    apply_frame, update_collision_wireframes,
                    update_collision_mesh_displays)
                frame = self.frames[value]
                apply_frame(frame)
                if self._wireframe_infos:
                    update_collision_wireframes(self._wireframe_infos, frame)
                if self._mesh_infos:
                    update_collision_mesh_displays(self._mesh_infos, frame)
                if self._wireframe_infos or self._mesh_infos:
                    FreeCADGui.updateGui()
                self._update_frame_label(value)
        except RuntimeError:
            pass

    def _go_start(self):
        if self._closed:
            return
        self._stop()
        self.slider.setValue(0)

    def _go_end(self):
        if self._closed:
            return
        self._stop()
        self.slider.setValue(len(self.frames) - 1)

    def _step_back(self):
        if self._closed:
            return
        self._stop()
        self.slider.setValue(max(0, self.slider.value() - 1))

    def _step_forward(self):
        if self._closed:
            return
        self._stop()
        self.slider.setValue(min(len(self.frames) - 1, self.slider.value() + 1))

    def _toggle_play(self):
        if self._closed:
            return
        if self._playing:
            self._stop()
        else:
            self._start_play()

    def _start_play(self):
        self._playing = True
        try:
            self.btn_play.setIcon(
                self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))
        except RuntimeError:
            pass
        ms = max(1, int(self.time_step * 1000 / self._speed_multiplier()))
        self.timer.start(ms)

    def _stop(self):
        self._playing = False
        self.timer.stop()
        try:
            self.btn_play.setIcon(
                self.form.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        except RuntimeError:
            pass

    def _advance(self):
        if self._closed:
            self.timer.stop()
            return
        try:
            next_idx = self.slider.value() + 1
            if next_idx >= len(self.frames):
                if self.loop_chk.isChecked():
                    next_idx = 0
                else:
                    self._stop()
                    return
            self.slider.setValue(next_idx)
        except RuntimeError:
            # Widget already destroyed (dialog closed while timer was running).
            self.timer.stop()

    def _reset(self):
        """Restore every Link to the placement it had before simulation."""
        self._stop()
        from ..simulation.BulletSimulation import collect_rigid_bodies
        for rb in collect_rigid_bodies():
            try:
                rb.BodyLink.Placement = rb.OriginalObject.Placement.copy()
            except Exception:
                pass
        FreeCADGui.updateGui()
        # Re-apply frame 0 so delayed emitter links are hidden again while
        # emissions scheduled at time zero remain visible.
        if self.frames:
            from ..simulation.BulletSimulation import apply_frame
            apply_frame(self.frames[0])
            self.slider.blockSignals(True)
            self.slider.setValue(0)
            self.slider.blockSignals(False)
            self._update_frame_label(0)
        # Wireframes / mesh displays: sync back to frame 0
        if self._wireframe_infos:
            if self.frames:
                from ..simulation.BulletSimulation import update_collision_wireframes
                update_collision_wireframes(self._wireframe_infos, self.frames[0])
            else:
                self._rebuild_wireframes()
        if self._mesh_infos:
            if self.frames:
                from ..simulation.BulletSimulation import update_collision_mesh_displays
                update_collision_mesh_displays(self._mesh_infos, self.frames[0])
            else:
                self._rebuild_mesh_displays()
        if self._wireframe_infos or self._mesh_infos:
            FreeCADGui.updateGui()

    def _delete_cache(self):
        from ..simulation.BulletSimulation import delete_simulation_cache
        deleted = delete_simulation_cache()
        if deleted:
            self._clear_playback("Cache deleted.")
        else:
            self.sim_status.setText("No cache file found.")

    def _show_speed_graph(self):
        if len(self.frames) < 2:
            self.sim_status.setText("Run or load a simulation before plotting speed.")
            return
        try:
            from ..simulation.BulletAnalytics import show_speed_plot
            show_speed_plot(
                self.frames, self.time_step, self.speed_graph_axis.currentText(),
                self.speed_frames)
        except (RuntimeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(None, "Speed Graph", str(exc))

    def _clear_playback(self, status_msg=""):
        self._stop()
        self.frames = []
        self.speed_frames = []
        self.time_step = 1.0 / 60.0
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.speed_combo.setEnabled(False)
        self.bake_btn.setEnabled(False)
        for btn in (self.btn_start, self.btn_back, self.btn_play,
                    self.btn_forward, self.btn_end):
            btn.setEnabled(False)
        self._update_frame_label(0)
        if status_msg:
            self.sim_status.setText(status_msg)

    def _bake_frame(self):
        """
        Copy the current frame's placements to the OriginalObjects so this
        pose becomes the new starting point for CAD work and future simulations.
        Recorded inside a FreeCAD transaction → fully undoable with Ctrl+Z.
        """
        if not self.frames:
            return
        self._stop()
        frame_idx = self.slider.value()
        frame     = self.frames[frame_idx]

        from ..simulation.BulletSimulation import (
            collect_rigid_bodies, delete_simulation_cache)

        doc = FreeCAD.ActiveDocument
        doc.openTransaction(f"Bake simulation frame {frame_idx} as new origin")
        try:
            for rb in collect_rigid_bodies():
                if rb.BodyType == "Passive":
                    continue
                link_name = rb.BodyLink.Name
                new_pl = frame.get(link_name, rb.BodyLink.Placement)
                rb.OriginalObject.Placement = new_pl.copy()
                rb.BodyLink.Placement       = new_pl.copy()
            doc.commitTransaction()
        except Exception as exc:
            doc.abortTransaction()
            FreeCAD.Console.PrintError(
                f"BulletPhysics: bake failed — {exc}\n")
            return

        FreeCADGui.updateGui()
        delete_simulation_cache()
        self._hide_wireframes()
        self.collision_chk.setChecked(False)
        self._hide_mesh_displays()
        if self._show_collision_mesh():
            self._rebuild_mesh_displays()
        t = frame_idx * self.time_step
        self._clear_playback(
            f"Frame {frame_idx} ({t:.3f} s) baked as new origin. "
            f"Re-run simulation to continue from this pose.")

    # ── Collision wireframes ─────────────────────────────────────────────────

    def _on_collision_chk(self, state):
        if state:
            self._rebuild_wireframes()
            self.refresh_collision_btn.setEnabled(True)
        else:
            self._hide_wireframes()

    def _rebuild_wireframes(self):
        """(Re)create wireframes from the current OriginalObject placements."""
        from ..simulation.BulletSimulation import (
            create_collision_wireframes, update_collision_wireframes,
            remove_collision_wireframes)
        if self._wireframe_infos:
            remove_collision_wireframes(self._wireframe_infos)
        self._wireframe_infos = create_collision_wireframes()
        if self.frames and self._wireframe_infos:
            update_collision_wireframes(
                self._wireframe_infos, self.frames[self.slider.value()])
            FreeCADGui.updateGui()

    def _hide_wireframes(self):
        from ..simulation.BulletSimulation import remove_collision_wireframes
        if self._wireframe_infos:
            remove_collision_wireframes(self._wireframe_infos)
            self._wireframe_infos = []
        self.refresh_collision_btn.setEnabled(False)

    @staticmethod
    def _show_collision_mesh():
        from ..simulation.BulletSimulation import _find_mesh_settings
        settings = _find_mesh_settings()
        if settings is None:
            return False
        if hasattr(settings.Proxy, "onDocumentRestored"):
            settings.Proxy.onDocumentRestored(settings)
        return getattr(settings, "ShowCollisionMesh", False)

    def _rebuild_mesh_displays(self):
        """(Re)create tessellated mesh displays from the current OriginalObject placements."""
        from ..simulation.BulletSimulation import (
            create_collision_mesh_displays, update_collision_mesh_displays,
            remove_collision_mesh_displays)
        if self._mesh_infos:
            remove_collision_mesh_displays(self._mesh_infos)
        self._mesh_infos = create_collision_mesh_displays()
        if self.frames and self._mesh_infos:
            update_collision_mesh_displays(
                self._mesh_infos, self.frames[self.slider.value()])
            FreeCADGui.updateGui()

    def _hide_mesh_displays(self):
        from ..simulation.BulletSimulation import remove_collision_mesh_displays
        if self._mesh_infos:
            remove_collision_mesh_displays(self._mesh_infos)
            self._mesh_infos = []

    def reject(self):
        self._closed = True
        self._sim_stop_requested = True
        self._sim_paused = False
        self._stop()
        self._hide_wireframes()
        FreeCADGui.Control.closeDialog()


# ---------------------------------------------------------------------------
# FreeCAD command
# ---------------------------------------------------------------------------

class RunSimulationCommand:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(_icons_path(), "RunSimulation.svg"),
            "MenuText": "Run Simulation",
            "ToolTip": "Simulate and play back with timeline. Settings from Physics World.",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        from ..objects.BulletContainer import find_container
        from ..objects.BulletRunSimulation import make_run_simulation
        container = find_container()
        if container is not None and getattr(container, "RunSimulation", None) is None:
            if hasattr(container.Proxy, "onDocumentRestored"):
                container.Proxy.onDocumentRestored(container)
            make_run_simulation(container)
            FreeCAD.ActiveDocument.recompute()
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Control.showDialog(SimulationPanel())


FreeCADGui.addCommand("BulletPhysics_RunSimulation", RunSimulationCommand())
