import FreeCAD

MM_TO_M = 0.001
M_TO_MM = 1000.0


def collect_rigid_bodies():
    """Return all BulletRigidBody objects that have a valid linked shape."""
    doc = FreeCAD.ActiveDocument
    result = []
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and hasattr(obj, "LinkedObject")
                and hasattr(obj, "BodyType")
                and obj.LinkedObject is not None
                and hasattr(obj.LinkedObject, "Shape")):
            result.append(obj)
    return result


def apply_frame(frame):
    """Apply a recorded frame dict {obj_name: Placement} to the active document."""
    import FreeCADGui
    doc = FreeCAD.ActiveDocument
    for obj_name, placement in frame.items():
        obj = doc.getObject(obj_name)
        if obj is not None:
            obj.Placement = placement
    FreeCADGui.updateGui()


def run_simulation(steps=500, time_step=1.0 / 60.0, callback=None):
    """
    Run the Bullet Physics simulation and return recorded frames.

    Returns
    -------
    list of dict  –  frames[0] is the initial state; frames[i] is the state
                     after i physics steps.  Each dict maps linked-object Name
                     to a FreeCAD.Placement.
    Returns None on error (missing pybullet, no rigid bodies, etc.).
    """
    try:
        import pybullet as p
    except ImportError:
        _show_install_error()
        return None

    rigid_bodies = collect_rigid_bodies()
    if not rigid_bodies:
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: No rigid body objects found.\n"
            "Select a solid and use 'Add Active/Passive Rigid Body' first.\n"
        )
        return None

    client = p.connect(p.DIRECT)
    p.setGravity(0, 0, -9.81, physicsClientId=client)
    p.setTimeStep(time_step, physicsClientId=client)

    # {bullet_body_id: (rb_doc_obj, linked_obj, local_offset_mm)}
    body_map = {}

    try:
        for rb in rigid_bodies:
            linked = rb.LinkedObject
            shape = linked.Shape
            bb = shape.BoundBox

            half = [bb.XLength * MM_TO_M / 2.0,
                    bb.YLength * MM_TO_M / 2.0,
                    bb.ZLength * MM_TO_M / 2.0]
            center_m = [bb.Center.x * MM_TO_M,
                        bb.Center.y * MM_TO_M,
                        bb.Center.z * MM_TO_M]

            col = p.createCollisionShape(
                p.GEOM_BOX, halfExtents=half, physicsClientId=client)

            pl = linked.Placement
            rot_q = pl.Rotation.Q          # (x, y, z, w)
            mass = rb.Mass if rb.BodyType == "Active" else 0.0

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

            # Local offset from placement origin to bbox centre (in local space)
            world_center = FreeCAD.Vector(
                bb.Center.x, bb.Center.y, bb.Center.z)
            local_offset = pl.Rotation.inverted().multVec(
                world_center - pl.Base)

            body_map[body_id] = (rb, linked, local_offset)

        # --- frame 0: initial placements (before any stepping) ---
        initial_frame = {
            linked.Name: linked.Placement.copy()
            for _, (rb, linked, _) in body_map.items()
            if rb.BodyType == "Active"
        }
        frames = [initial_frame]

        # --- simulation loop ---
        for step in range(steps):
            p.stepSimulation(physicsClientId=client)

            frame = {}
            for body_id, (rb, linked, local_offset) in body_map.items():
                if rb.BodyType == "Passive":
                    continue
                pos, orn = p.getBasePositionAndOrientation(
                    body_id, physicsClientId=client)

                new_rot = FreeCAD.Rotation(orn[0], orn[1], orn[2], orn[3])
                new_world_center = FreeCAD.Vector(
                    pos[0] * M_TO_MM, pos[1] * M_TO_MM, pos[2] * M_TO_MM)
                new_base = new_world_center - new_rot.multVec(local_offset)
                frame[linked.Name] = FreeCAD.Placement(new_base, new_rot)

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
        "  python3 -m pip install pybullet --break-system-packages\n\n"
        "(On openSUSE, first: sudo zypper install python313-devel)",
    )
