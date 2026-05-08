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

def _detect_freecad_shape_type(fc_shape):
    """
    Return 'sphere', 'cylinder', or 'box' by inspecting FreeCAD face surfaces.
    Falls back to 'box' for anything unrecognised.
    """
    faces = fc_shape.Faces
    if not faces:
        return "box"

    surface_class_names = []
    for face in faces:
        try:
            surface_class_names.append(type(face.Surface).__name__)
        except Exception:
            surface_class_names.append("")

    # Sphere: single face whose Surface is a Part.Sphere
    if len(faces) == 1 and "Sphere" in surface_class_names[0]:
        return "sphere"

    # Cylinder: three faces — one cylindrical + two planar caps
    if len(faces) == 3 and any("Cylinder" in n for n in surface_class_names):
        return "cylinder"

    return "box"


def _make_collision_shape(p, fc_shape, half_extents, client):
    """
    Create the most accurate pybullet collision shape for *fc_shape*.

    Returns (collision_shape_id, characteristic_radius_m) where
    characteristic_radius is a representative size used for CCD thresholds.
    """
    shape_type = _detect_freecad_shape_type(fc_shape)
    hx, hy, hz = half_extents

    if shape_type == "sphere":
        # Use the average of the three half-extents as the radius (handles
        # slight floating-point asymmetry in the bounding box).
        radius = (hx + hy + hz) / 3.0
        col = p.createCollisionShape(
            p.GEOM_SPHERE, radius=radius, physicsClientId=client)
        return col, radius

    if shape_type == "cylinder":
        # The cylinder axis is the tallest bbox dimension.
        # pybullet GEOM_CYLINDER is always Z-axis aligned; we match that by
        # choosing the tallest half-extent as the half-height.
        half_sorted = sorted([hx, hy, hz])
        radius    = (half_sorted[0] + half_sorted[1]) / 2.0
        halfHeight = half_sorted[2]
        col = p.createCollisionShape(
            p.GEOM_CYLINDER,
            radius=radius,
            height=halfHeight * 2.0,
            physicsClientId=client,
        )
        return col, radius

    # Default: axis-aligned box
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
        import pybullet as p
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
        gravity_mag   = world.Gravity
        gravity_dir   = world.GravityDirection
        time_step     = world.TimeStep
        steps         = world.Steps
        solver_iters  = world.SolverIterations
        sub_steps     = max(1, world.SubSteps)
    else:
        gravity_mag   = 9.81
        gravity_dir   = FreeCAD.Vector(0, 0, -1)
        time_step     = 1.0 / 60.0
        steps         = 500
        solver_iters  = 10
        sub_steps     = 4

    # Normalise direction
    d = gravity_dir
    length = (d.x**2 + d.y**2 + d.z**2) ** 0.5
    if length < 1e-9:
        length = 1.0
    gx = d.x / length * gravity_mag
    gy = d.y / length * gravity_mag
    gz = d.z / length * gravity_mag

    FreeCAD.Console.PrintMessage(
        f"BulletPhysics: starting simulation — "
        f"steps={steps}, Δt={time_step*1000:.3f} ms, "
        f"subSteps={sub_steps}, "
        f"gravity=({gx:.3f}, {gy:.3f}, {gz:.3f}) m/s², "
        f"solverIterations={solver_iters}\n"
    )

    client = p.connect(p.DIRECT)
    p.setGravity(gx, gy, gz, physicsClientId=client)
    p.setTimeStep(time_step, physicsClientId=client)
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

            col, characteristic_radius = _make_collision_shape(
                p, shape, half, client)

            rot_q = orig_pl.Rotation.Q      # (x, y, z, w)
            mass  = rb.Mass if rb.BodyType == "Active" else 0.0

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

            # Enable CCD for active bodies so fast-moving objects don't tunnel
            # through thin surfaces between steps.  Setting ccdSweptSphereRadius
            # to a fraction of the object size activates Bullet's swept-sphere CCD.
            if mass > 0:
                p.changeDynamics(
                    body_id, -1,
                    ccdSweptSphereRadius=characteristic_radius * 0.4,
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
                callback(step + 1, steps)

        return frames

    finally:
        p.disconnect(client)


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
