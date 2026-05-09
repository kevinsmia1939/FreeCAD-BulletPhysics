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

    # {bullet_id: (rb_doc_obj, link_obj, local_offset_mm)}
    body_map = {}

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

            # Half-extents from the original shape geometry
            half = [bb.XLength * MM_TO_M / 2.0,
                    bb.YLength * MM_TO_M / 2.0,
                    bb.ZLength * MM_TO_M / 2.0]

            # World-space bbox centre (original never moves, so this is stable)
            world_center = FreeCAD.Vector(
                bb.Center.x, bb.Center.y, bb.Center.z)
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

            # Local offset: placement origin → bbox centre in object's local frame
            local_offset = orig_pl.Rotation.inverted().multVec(
                world_center - orig_pl.Base)

            body_map[body_id] = (rb, link, local_offset)

        # Frame 0 — initial placements of all Links (before any stepping)
        initial_frame = {}
        for _, (rb, link, _) in body_map.items():
            initial_frame[link.Name] = link.Placement.copy()
        frames = [initial_frame]

        # Simulation loop — each recorded frame runs sub_steps Bullet ticks
        for step in range(steps):
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
