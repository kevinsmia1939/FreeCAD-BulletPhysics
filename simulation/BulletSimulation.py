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
    else:
        gravity_mag   = 9.81
        gravity_dir   = FreeCAD.Vector(0, 0, -1)
        time_step     = 1.0 / 60.0
        steps         = 500
        solver_iters  = 10

    # Normalise direction
    d = gravity_dir
    length = (d.x**2 + d.y**2 + d.z**2) ** 0.5
    if length < 1e-9:
        length = 1.0
    gx = d.x / length * gravity_mag
    gy = d.y / length * gravity_mag
    gz = d.z / length * gravity_mag

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

            shape = original.Shape
            bb = shape.BoundBox

            # Half-extents from the original shape geometry
            half = [bb.XLength * MM_TO_M / 2.0,
                    bb.YLength * MM_TO_M / 2.0,
                    bb.ZLength * MM_TO_M / 2.0]

            # Initial world-space centre: use original bbox centre
            # (link starts at the same placement as original was at creation time)
            world_center = FreeCAD.Vector(
                bb.Center.x, bb.Center.y, bb.Center.z)
            center_m = [world_center.x * MM_TO_M,
                        world_center.y * MM_TO_M,
                        world_center.z * MM_TO_M]

            col = p.createCollisionShape(
                p.GEOM_BOX, halfExtents=half, physicsClientId=client)

            link_pl = link.Placement
            rot_q   = link_pl.Rotation.Q      # (x, y, z, w)
            mass    = rb.Mass if rb.BodyType == "Active" else 0.0

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

            # Local offset: from link-placement origin to bbox centre, in link's local frame
            local_offset = link_pl.Rotation.inverted().multVec(
                world_center - link_pl.Base)

            body_map[body_id] = (rb, link, local_offset)

        # Frame 0 — initial placements of all Links (before any stepping)
        initial_frame = {}
        for _, (rb, link, _) in body_map.items():
            initial_frame[link.Name] = link.Placement.copy()
        frames = [initial_frame]

        # Simulation loop
        for step in range(steps):
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
