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
        self._wireframe_infos = []
        self._sim_stop_requested = False

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
        root.addStretch()

        # ── Timer ─────────────────────────────────────────────────────────────
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._advance)

        # ── Wiring ────────────────────────────────────────────────────────────
        self.sim_btn.clicked.connect(self._run_simulation)
        self.stop_sim_btn.clicked.connect(self._stop_simulation)
        self.reset_btn.clicked.connect(self._reset)
        self.delete_cache_btn.clicked.connect(self._delete_cache)
        self.bake_btn.clicked.connect(self._bake_frame)
        self.slider.valueChanged.connect(self._on_slider)
        self.btn_start.clicked.connect(self._go_start)
        self.btn_back.clicked.connect(self._step_back)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_forward.clicked.connect(self._step_forward)
        self.btn_end.clicked.connect(self._go_end)
        self.speed_combo.currentIndexChanged.connect(self._update_timer_interval)

        self.collision_chk.stateChanged.connect(self._on_collision_chk)
        self.refresh_collision_btn.clicked.connect(self._rebuild_wireframes)

        self._refresh_world_label()
        from simulation.BulletSimulation import cleanup_stale_wireframes
        cleanup_stale_wireframes()
        self._try_load_cache()

    # ── World info ──────────────────────────────────────────────────────────

    def _refresh_world_label(self):
        from objects.BulletWorld import find_world
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
        from simulation.BulletSimulation import run_simulation
        self._stop()
        self._refresh_world_label()
        self._sim_stop_requested = False
        self.sim_btn.setEnabled(False)
        self.stop_sim_btn.setEnabled(True)
        self.progress.setValue(0)
        self.sim_status.setText("Running…")

        def cb(done, total):
            self.progress.setValue(int(done * 100 / total))
            QtWidgets.QApplication.processEvents()
            if self._sim_stop_requested:
                return False  # signal run_simulation to break early

        result = run_simulation(callback=cb)
        self.sim_btn.setEnabled(True)
        self.stop_sim_btn.setEnabled(False)

        if not result:
            self.sim_status.setText("Simulation failed — see Report View.")
            return

        self.frames, self.time_step = result
        from simulation.BulletSimulation import save_simulation_cache
        save_simulation_cache(self.frames, self.time_step)
        self._populate_playback(apply_first_frame=True)
        if self.collision_chk.isChecked():
            self._rebuild_wireframes()
        n = len(self.frames) - 1
        total_secs = n * self.time_step
        stopped = " (stopped early)" if self._sim_stop_requested else ""
        self.sim_status.setText(
            f"Done — {n} frames  ({total_secs:.2f} s simulated){stopped}")

    def _stop_simulation(self):
        self._sim_stop_requested = True
        self.stop_sim_btn.setEnabled(False)
        self.sim_status.setText("Stopping…")

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
        self.bake_btn.setEnabled(True)
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
            from simulation.BulletSimulation import apply_frame, update_collision_wireframes
            frame = self.frames[value]
            apply_frame(frame)
            if self._wireframe_infos:
                update_collision_wireframes(self._wireframe_infos, frame)
                FreeCADGui.updateGui()
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
        # Wireframes: rebuild from original placements (frame 0)
        if self._wireframe_infos:
            if self.frames:
                from simulation.BulletSimulation import update_collision_wireframes
                update_collision_wireframes(self._wireframe_infos, self.frames[0])
            else:
                self._rebuild_wireframes()
            FreeCADGui.updateGui()

    def _delete_cache(self):
        from simulation.BulletSimulation import delete_simulation_cache
        deleted = delete_simulation_cache()
        if deleted:
            self._clear_playback("Cache deleted.")
        else:
            self.sim_status.setText("No cache file found.")

    def _clear_playback(self, status_msg=""):
        self._stop()
        self.frames = []
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

        from simulation.BulletSimulation import (
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
        from simulation.BulletSimulation import (
            create_collision_wireframes, update_collision_wireframes,
            remove_collision_wireframes)
        if self._wireframe_infos:
            remove_collision_wireframes(self._wireframe_infos)
        self._wireframe_infos = create_collision_wireframes()
        # If a frame is already loaded, advance wireframes to the current frame
        if self.frames and self._wireframe_infos:
            update_collision_wireframes(
                self._wireframe_infos, self.frames[self.slider.value()])
            FreeCADGui.updateGui()

    def _hide_wireframes(self):
        from simulation.BulletSimulation import remove_collision_wireframes
        if self._wireframe_infos:
            remove_collision_wireframes(self._wireframe_infos)
            self._wireframe_infos = []
        self.refresh_collision_btn.setEnabled(False)

    def reject(self):
        self._stop()
        self._hide_wireframes()
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
