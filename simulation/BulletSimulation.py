import FreeCAD

MM_TO_M = 0.001
M_TO_MM = 1000.0


# ---------------------------------------------------------------------------
# Document-object helpers
# ---------------------------------------------------------------------------

def collect_rigid_bodies(doc=None):
    """Return all BulletRigidBody objects that have a valid BodyLink."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    result = []
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "RigidBodyFeature"
                and hasattr(obj, "BodyLink")
                and obj.BodyLink is not None
                and hasattr(obj, "OriginalObject")
                and obj.OriginalObject is not None
                and hasattr(obj.OriginalObject, "Shape")):
            result.append(obj)
    return result


def collect_launchers(doc=None):
    """Return all BulletLauncher objects that have a valid TargetBody."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    result = []
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletLauncherFeature"
                and hasattr(obj, "TargetBody")
                and obj.TargetBody is not None):
            result.append(obj)
    return result


def apply_frame(frame, doc=None):
    """
    Apply one recorded frame to the active document.

    *frame* maps App::Link object Name → FreeCAD.Placement.
    Only Link objects are updated; originals are never touched.
    """
    import FreeCADGui
    if doc is None:
        doc = FreeCAD.ActiveDocument
    for link_name, placement in frame.items():
        obj = doc.getObject(link_name)
        if obj is not None:
            obj.Placement = placement
    FreeCADGui.updateGui()


# ---------------------------------------------------------------------------
# Collision shape factory
# ---------------------------------------------------------------------------

def _surface_type_names(fc_shape):
    names = []
    for face in fc_shape.Faces:
        try:
            names.append(type(face.Surface).__name__)
        except Exception:
            names.append("")
    return names


def _detect_freecad_shape_type(fc_shape):
    """
    Classify fc_shape as 'sphere', 'cylinder', 'box', or 'mesh'.

    'mesh' is returned for any custom or irregular solid so that it gets
    an accurate tessellated collision shape instead of a bounding box.
    """
    faces = fc_shape.Faces
    if not faces:
        return "box"

    names = _surface_type_names(fc_shape)

    # Sphere: one face with a spherical surface
    if len(faces) == 1 and "Sphere" in names[0]:
        return "sphere"

    # Cylinder: 3 faces — one cylindrical lateral + two planar caps
    if len(faces) == 3 and any("Cylinder" in n for n in names):
        return "cylinder"

    # Box: exactly 6 planar faces (Part::Box, or any extruded rectangle)
    if len(faces) == 6 and all("Plane" in n for n in names):
        return "box"

    # Cone: 2 faces (one conical, one planar base) — use mesh
    # Any other solid with curved or mixed faces — use mesh
    return "mesh"


def _local_half_extents(fc_shape, orig_pl):
    """
    Return [hx, hy, hz] in mm — the collision shape half-extents in the body's
    own local frame.  Computed by inverse-rotating the world-space vertices so
    the AABB of a rotated shape is not inflated.
    """
    inv_rot = orig_pl.Rotation.inverted()
    local_pts = [inv_rot.multVec(v.Point) for v in fc_shape.Vertexes]
    if local_pts:
        lxs = [lp.x for lp in local_pts]
        lys = [lp.y for lp in local_pts]
        lzs = [lp.z for lp in local_pts]
        return [(max(lxs) - min(lxs)) / 2.0,
                (max(lys) - min(lys)) / 2.0,
                (max(lzs) - min(lzs)) / 2.0]
    bb = fc_shape.BoundBox
    return [bb.XLength / 2.0, bb.YLength / 2.0, bb.ZLength / 2.0]


def _tessellate_to_local(fc_shape, orig_pl, world_center, precision):
    """
    Tessellate fc_shape and return (vertices, flat_indices) in body-local space.

    Body-local space is centred at world_center (the bbox centre) and has the
    same orientation as orig_pl.  Coordinates are in metres.

    *precision* is the maximum chord deviation in mm (from MeshResolution).
    """
    verts_world, tri_faces = fc_shape.tessellate(precision)
    if not verts_world or not tri_faces:
        raise ValueError("tessellate() returned an empty mesh")

    inv_rot = orig_pl.Rotation.inverted()
    verts_local = []
    for v in verts_world:
        # Translate to bbox-centre-relative, then rotate into body-local frame
        rel = FreeCAD.Vector(v.x - world_center.x,
                             v.y - world_center.y,
                             v.z - world_center.z)
        lv = inv_rot.multVec(rel)
        verts_local.append([lv.x * MM_TO_M, lv.y * MM_TO_M, lv.z * MM_TO_M])

    flat_indices = [i for tri in tri_faces for i in tri]
    return verts_local, flat_indices


def _make_collision_shape(p, fc_shape, half_extents, orig_pl, world_center,
                          client, is_static=False, mesh_resolution=1.0):
    """
    Create the most accurate pybullet collision shape for fc_shape.

    For recognised primitives (sphere, cylinder, box) the exact analytic shape
    is used.  For any other solid a mesh is tessellated from the FreeCAD shape:
      - static bodies  (mass=0): full triangle mesh → exact concave collision
      - dynamic bodies (mass>0): convex hull  → pybullet builds it automatically

    Returns (collision_shape_id, characteristic_radius_m).
    """
    shape_type = _detect_freecad_shape_type(fc_shape)
    hx, hy, hz = half_extents

    if shape_type == "sphere":
        radius = (hx + hy + hz) / 3.0
        col = p.createCollisionShape(
            p.GEOM_SPHERE, radius=radius, physicsClientId=client)
        return col, radius

    if shape_type == "cylinder":
        half_sorted = sorted([hx, hy, hz])
        radius     = (half_sorted[0] + half_sorted[1]) / 2.0
        halfHeight = half_sorted[2]
        col = p.createCollisionShape(
            p.GEOM_CYLINDER,
            radius=radius,
            height=halfHeight * 2.0,
            physicsClientId=client,
        )
        return col, radius

    if shape_type == "box":
        col = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=half_extents, physicsClientId=client)
        return col, min(half_extents)

    # --- Custom mesh shape ---
    try:
        verts, indices = _tessellate_to_local(
            fc_shape, orig_pl, world_center, mesh_resolution)

        flags = (p.GEOM_CONCAVE_INTERNAL_EDGE if is_static else 0)
        col = p.createCollisionShape(
            p.GEOM_MESH,
            vertices=verts,
            indices=indices,
            flags=flags,
            physicsClientId=client,
        )
        kind = "concave mesh" if is_static else "convex-hull mesh"
        FreeCAD.Console.PrintMessage(
            f"BulletPhysics: {kind} ({len(verts)} verts, "
            f"{len(indices)//3} tris, res={mesh_resolution} mm) for custom shape\n"
        )
        return col, min(half_extents)

    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            f"BulletPhysics: mesh failed ({exc}), falling back to bounding box\n"
        )
        col = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=half_extents, physicsClientId=client)
        return col, min(half_extents)


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def run_simulation(callback=None):
    """
    Run the Bullet Physics simulation using settings from the BulletWorld object.

    Returns a list of frame dicts (frame[0] = initial state).
    Each frame maps App::Link.Name → FreeCAD.Placement.
    Returns None on error.
    """
    try:
        import sys
        from preferences.BulletPreferences import get_pybullet_path
        _custom_path = get_pybullet_path()
        _path_inserted = False
        if _custom_path and _custom_path not in sys.path:
            sys.path.insert(0, _custom_path)
            _path_inserted = True
        import pybullet as p
        if _path_inserted:
            sys.path.remove(_custom_path)
    except ImportError:
        _show_install_error()
        return None

    from objects.BulletWorld import find_world

    rigid_bodies = collect_rigid_bodies()
    if not rigid_bodies:
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: No rigid body objects found.\n"
            "Add Active/Passive rigid bodies inside a Physics Container first.\n"
        )
        return None

    # --- Physics World settings ---
    world = find_world()
    if world:
        # _ensure_properties patches any property missing from objects created
        # by an older version of the workbench (live session, no save/load needed)
        if hasattr(world.Proxy, "_ensure_properties"):
            world.Proxy._ensure_properties(world)

        gravity_mag      = world.Gravity
        gravity_dir      = world.GravityDirection
        end_time         = max(0.001, getattr(world, "EndTime", 10.0))
        time_step        = world.TimeStep
        solver_iters     = world.SolverIterations
        sub_steps        = max(1, getattr(world, "SubSteps", 4))
        mesh_resolution  = max(0.001, getattr(world, "MeshResolution", 1.0))
        linear_damping   = max(0.0, min(1.0, getattr(world, "LinearDamping", 0.0)))
        angular_damping  = max(0.0, min(1.0, getattr(world, "AngularDamping", 0.0)))
    else:
        gravity_mag      = 9.81
        gravity_dir      = FreeCAD.Vector(0, 0, -1)
        end_time         = 10.0
        time_step        = 1.0 / 60.0
        solver_iters     = 10
        sub_steps        = 4
        mesh_resolution  = 1.0
        linear_damping   = 0.0
        angular_damping  = 0.0

    steps = max(1, round(end_time / time_step))

    # Normalise direction
    d = gravity_dir
    length = (d.x**2 + d.y**2 + d.z**2) ** 0.5
    if length < 1e-9:
        length = 1.0
    gx = d.x / length * gravity_mag
    gy = d.y / length * gravity_mag
    gz = d.z / length * gravity_mag

    # Each recorded frame covers exactly time_step seconds.  Sub-stepping
    # divides that interval into sub_steps smaller Bullet ticks for better
    # collision accuracy without changing playback speed or total duration.
    bullet_tick = time_step / sub_steps

    FreeCAD.Console.PrintMessage(
        f"BulletPhysics: starting simulation — "
        f"endTime={end_time:.3f} s, steps={steps}, "
        f"frame={time_step*1000:.3f} ms, "
        f"subSteps={sub_steps}, tick={bullet_tick*1000:.3f} ms, "
        f"gravity=({gx:.3f}, {gy:.3f}, {gz:.3f}) m/s², "
        f"solverIterations={solver_iters}, "
        f"linearDamping={linear_damping:.3f}, angularDamping={angular_damping:.3f}\n"
    )

    client = p.connect(p.DIRECT)
    p.setGravity(gx, gy, gz, physicsClientId=client)
    p.setTimeStep(bullet_tick, physicsClientId=client)
    p.setPhysicsEngineParameter(
        numSolverIterations=solver_iters, physicsClientId=client)

    launchers = collect_launchers()
    # Build a lookup: rb.Name -> launcher object  (last one wins if duplicates)
    launcher_by_rb = {ln.TargetBody.Name: ln for ln in launchers
                      if ln.TargetBody is not None}

    # {bullet_id: (rb_doc_obj, link_obj, local_offset_mm)}
    body_map = {}
    # {bullet_id: (fire_step, vel_x, vel_y, vel_z, actual_mass)}
    launch_map = {}

    try:
        for rb in rigid_bodies:
            original = rb.OriginalObject
            link     = rb.BodyLink

            # Always use the original object's placement as the ground truth for
            # the initial state.  The link may sit at the end of a previous
            # simulation run, so reading link.Placement would give wrong initial
            # orientation and a broken local_offset.
            orig_pl = original.Placement

            # Reset the link to the original position before building the world
            link.Placement = orig_pl.copy()

            shape = original.Shape
            bb = shape.BoundBox

            # World-space bbox centre (correct for any rotation — AABB centre
            # equals the geometric centre for convex symmetric shapes like boxes).
            world_center = FreeCAD.Vector(
                bb.Center.x, bb.Center.y, bb.Center.z)

            # Half-extents in body-local frame (mm → m).
            half_mm = _local_half_extents(shape, orig_pl)
            half = [h * MM_TO_M for h in half_mm]
            center_m = [world_center.x * MM_TO_M,
                        world_center.y * MM_TO_M,
                        world_center.z * MM_TO_M]

            is_static = (rb.BodyType == "Passive")
            body_res  = getattr(rb, "MeshResolution", 0.0)
            effective_res = body_res if body_res > 0 else mesh_resolution
            col, characteristic_radius = _make_collision_shape(
                p, shape, half, orig_pl, world_center, client,
                is_static=is_static, mesh_resolution=effective_res)

            rot_q = orig_pl.Rotation.Q      # (x, y, z, w)
            if rb.BodyType == "Active":
                density    = getattr(rb, "Density", 1000.0)
                volume_m3  = shape.Volume * 1e-9   # mm³ → m³
                mass       = density * volume_m3
            else:
                mass = 0.0

            body_id = p.createMultiBody(
                baseMass=mass,
                baseCollisionShapeIndex=col,
                basePosition=center_m,
                baseOrientation=rot_q,
                physicsClientId=client,
            )
            p.changeDynamics(
                body_id, -1,
                restitution=rb.Restitution,
                lateralFriction=rb.Friction,
                physicsClientId=client,
            )

            # Active bodies: enable CCD, prevent sleep, apply air damping.
            # activationState=4 == DISABLE_DEACTIVATION in Bullet's enum.
            if mass > 0:
                p.changeDynamics(
                    body_id, -1,
                    ccdSweptSphereRadius=characteristic_radius * 0.4,
                    activationState=4,
                    linearDamping=linear_damping,
                    angularDamping=angular_damping,
                    physicsClientId=client,
                )

            # If this body has a launcher, freeze it (mass=0) until launch time.
            if rb.Name in launcher_by_rb and mass > 0:
                ln = launcher_by_rb[rb.Name]
                p.changeDynamics(body_id, -1, mass=0, physicsClientId=client)

                # Normalise direction
                d = ln.Direction
                dlen = (d.x**2 + d.y**2 + d.z**2) ** 0.5
                if dlen < 1e-9:
                    dlen = 1.0
                speed = max(0.0, ln.Velocity)
                vx = d.x / dlen * speed
                vy = d.y / dlen * speed
                vz = d.z / dlen * speed

                fire_step = max(0, int(ln.LaunchTime / time_step))
                launch_map[body_id] = (fire_step, vx, vy, vz, mass,
                                       characteristic_radius)
                FreeCAD.Console.PrintMessage(
                    f"BulletPhysics: launcher '{ln.Label}' → '{rb.Label}' "
                    f"fires at step {fire_step} "
                    f"(t={fire_step * time_step:.3f} s), "
                    f"v=({vx:.2f}, {vy:.2f}, {vz:.2f}) m/s\n"
                )

            # Local offset: placement origin → bbox centre in object's local frame
            local_offset = orig_pl.Rotation.inverted().multVec(
                world_center - orig_pl.Base)

            body_map[body_id] = (rb, link, local_offset)

        # Frame 0 — initial placements of all Links (before any stepping)
        initial_frame = {}
        for _, (rb, link, _) in body_map.items():
            initial_frame[link.Name] = link.Placement.copy()
        frames = [initial_frame]

        fired_launchers = set()

        # Simulation loop — each recorded frame runs sub_steps Bullet ticks
        for step in range(steps):
            # Fire any launchers whose time has come (before stepping this frame)
            for body_id, (fire_step, vx, vy, vz, actual_mass, char_r) in launch_map.items():
                if step == fire_step and body_id not in fired_launchers:
                    p.changeDynamics(
                        body_id, -1,
                        mass=actual_mass,
                        ccdSweptSphereRadius=char_r * 0.4,
                        activationState=4,
                        linearDamping=linear_damping,
                        angularDamping=angular_damping,
                        physicsClientId=client,
                    )
                    p.resetBaseVelocity(
                        body_id,
                        linearVelocity=[vx, vy, vz],
                        angularVelocity=[0.0, 0.0, 0.0],
                        physicsClientId=client,
                    )
                    fired_launchers.add(body_id)

            for _ in range(sub_steps):
                p.stepSimulation(physicsClientId=client)

            frame = {}
            for body_id, (rb, link, local_offset) in body_map.items():
                if rb.BodyType == "Passive":
                    continue
                pos, orn = p.getBasePositionAndOrientation(
                    body_id, physicsClientId=client)

                new_rot = FreeCAD.Rotation(orn[0], orn[1], orn[2], orn[3])
                new_world_center = FreeCAD.Vector(
                    pos[0] * M_TO_MM,
                    pos[1] * M_TO_MM,
                    pos[2] * M_TO_MM,
                )
                new_base = new_world_center - new_rot.multVec(local_offset)
                frame[link.Name] = FreeCAD.Placement(new_base, new_rot)

            frames.append(frame)

            if callback:
                if callback(step + 1, steps) is False:
                    FreeCAD.Console.PrintMessage(
                        f"BulletPhysics: simulation stopped after {step + 1} frames.\n")
                    break

        return frames, time_step

    finally:
        p.disconnect(client)


# ---------------------------------------------------------------------------
# Simulation cache (persisted to disk next to the .FCStd file)
# ---------------------------------------------------------------------------

def _cache_path(doc=None):
    import os, tempfile
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return None
    if doc.FileName:
        base = os.path.splitext(doc.FileName)[0]
        return base + "_bullet_cache.json"
    return os.path.join(tempfile.gettempdir(),
                        f"freecad_bullet_{doc.Name}.json")


def save_simulation_cache(frames, time_per_frame, doc=None):
    import json
    path = _cache_path(doc)
    if path is None:
        return
    data = {
        "time_per_frame": time_per_frame,
        "frames": [
            {name: {"base": [pl.Base.x, pl.Base.y, pl.Base.z],
                    "rotation": list(pl.Rotation.Q)}
             for name, pl in frame.items()}
            for frame in frames
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f)
    FreeCAD.Console.PrintMessage(
        f"BulletPhysics: simulation cache saved → {path}\n")


def load_simulation_cache(doc=None):
    """Return (frames, time_per_frame) from the cache file, or None."""
    import json, os
    path = _cache_path(doc)
    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        time_per_frame = float(data["time_per_frame"])
        frames = []
        for fd in data["frames"]:
            frame = {}
            for name, pd in fd.items():
                b = pd["base"]
                r = pd["rotation"]
                frame[name] = FreeCAD.Placement(
                    FreeCAD.Vector(b[0], b[1], b[2]),
                    FreeCAD.Rotation(r[0], r[1], r[2], r[3]),
                )
            frames.append(frame)
        FreeCAD.Console.PrintMessage(
            f"BulletPhysics: loaded simulation cache ← {path}\n")
        return frames, time_per_frame
    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            f"BulletPhysics: could not load cache ({exc})\n")
        return None


def delete_simulation_cache(doc=None):
    """Delete the cache file for *doc*. Returns True if deleted, False if none existed."""
    import os
    path = _cache_path(doc)
    if path and os.path.exists(path):
        os.remove(path)
        FreeCAD.Console.PrintMessage(
            f"BulletPhysics: simulation cache deleted — {path}\n")
        return True
    return False


# ---------------------------------------------------------------------------
# Collision wireframe visualisation
# ---------------------------------------------------------------------------

def _build_collision_wireframe_shape(fc_shape, orig_pl):
    """
    Return (part_shape, local_offset_mm) where part_shape is a Part solid
    representing the collision envelope, centered at its local origin (so that
    setting Part::Feature.Placement = Placement(collision_center, rot) places
    it correctly in the 3D view).

    local_offset_mm is the FreeCAD-unit (mm) vector from orig_pl.Base to the
    collision centre, expressed in the body's local frame.
    """
    import Part

    bb = fc_shape.BoundBox
    world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
    inv_rot = orig_pl.Rotation.inverted()
    local_offset = inv_rot.multVec(world_center - orig_pl.Base)

    half = _local_half_extents(fc_shape, orig_pl)   # [hx, hy, hz] in mm
    shape_type = _detect_freecad_shape_type(fc_shape)

    if shape_type == "sphere":
        radius = (half[0] + half[1] + half[2]) / 3.0
        wf = Part.makeSphere(radius)
        # Part.makeSphere is already centred at origin — no transform needed

    elif shape_type == "cylinder":
        half_sorted = sorted(half)
        radius = (half_sorted[0] + half_sorted[1]) / 2.0
        height = half_sorted[2] * 2.0
        wf = Part.makeCylinder(radius, height)
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(0.0, 0.0, -height / 2.0))
        wf = wf.transformGeometry(mat)

    else:   # box or mesh — use an OBB-aligned box
        hx, hy, hz = half
        wf = Part.makeBox(hx * 2.0, hy * 2.0, hz * 2.0)
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(-hx, -hy, -hz))
        wf = wf.transformGeometry(mat)

    return wf, local_offset


def create_collision_wireframes(doc=None):
    """
    Create a green wireframe Part::Feature for every rigid body's collision
    envelope.  Works before the simulation is run (reads OriginalObject placements).

    Returns a list of (obj, link_name, local_offset_mm) tuples.
    local_offset_mm is the body-local vector (mm) from the placement origin to
    the collision centre — needed to reposition wireframes during playback.
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument
    result = []

    for rb in collect_rigid_bodies(doc):
        original  = rb.OriginalObject
        orig_pl   = original.Placement
        fc_shape  = original.Shape

        wf_shape, local_offset = _build_collision_wireframe_shape(fc_shape, orig_pl)

        obj = doc.addObject("Part::Feature", f"_BtWF_{rb.Label}")
        obj.Label  = f"Collision: {rb.Label}"
        obj.Shape  = wf_shape

        col_center = orig_pl.Base + orig_pl.Rotation.multVec(local_offset)
        obj.Placement = FreeCAD.Placement(col_center, orig_pl.Rotation)

        if FreeCAD.GuiUp:
            import FreeCADGui
            vobj = obj.ViewObject
            vobj.DisplayMode = "Wireframe"
            vobj.LineColor   = (0.0, 1.0, 0.0)
            vobj.LineWidth   = 2.0
            vobj.Selectable  = False

        result.append((obj, rb.BodyLink.Name, local_offset))

    doc.recompute()
    return result


def update_collision_wireframes(wireframe_infos, frame):
    """
    Reposition each wireframe to match the given simulation frame.
    Passive bodies are not in *frame*, so their wireframes stay in place
    (correct, since passive bodies do not move).
    """
    for (obj, link_name, local_offset) in wireframe_infos:
        if link_name not in frame:
            continue
        link_pl    = frame[link_name]
        col_center = link_pl.Base + link_pl.Rotation.multVec(local_offset)
        obj.Placement = FreeCAD.Placement(col_center, link_pl.Rotation)


def remove_collision_wireframes(wireframe_infos, doc=None):
    """Delete all wireframe objects from the document."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    for (obj, _, _) in wireframe_infos:
        try:
            doc.removeObject(obj.Name)
        except Exception:
            pass
    if wireframe_infos:
        doc.recompute()


def cleanup_stale_wireframes(doc=None):
    """Remove any leftover _BtWF_ objects (e.g. from a previous crash)."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return
    stale = [o for o in doc.Objects if o.Name.startswith("_BtWF_")]
    for o in stale:
        doc.removeObject(o.Name)
    if stale:
        doc.recompute()


def _show_install_error():
    try:
        from PySide2.QtWidgets import QMessageBox
    except ImportError:
        from PySide.QtWidgets import QMessageBox
    QMessageBox.critical(
        None,
        "pybullet not installed",
        "pybullet is required.\n\n"
        "  CFLAGS='-Wno-error=return-type' \\\n"
        "  CXXFLAGS='-Wno-error=return-type' \\\n"
        "  python3 -m pip install pybullet --break-system-packages",
    )
