import FreeCAD
import FreeCADGui

MM_TO_M = 0.001
M_TO_MM = 1000.0


def _collect_rigid_bodies():
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


def _bbox_half_extents(shape):
    bb = shape.BoundBox
    return [bb.XLength * MM_TO_M / 2.0,
            bb.YLength * MM_TO_M / 2.0,
            bb.ZLength * MM_TO_M / 2.0]


def _bbox_center_m(shape):
    c = shape.BoundBox.Center
    return [c.x * MM_TO_M, c.y * MM_TO_M, c.z * MM_TO_M]


def run_simulation(steps=500, time_step=1.0 / 60.0, callback=None):
    """
    Run the Bullet Physics simulation.

    steps      – number of physics steps to run
    time_step  – seconds per step
    callback   – optional callable(step, total) called each step for progress
    """
    try:
        import pybullet as p
    except ImportError:
        _show_install_error()
        return False

    rigid_bodies = _collect_rigid_bodies()
    if not rigid_bodies:
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: No rigid body objects found in document.\n"
            "Select a solid and use 'Add Active/Passive Rigid Body' first.\n"
        )
        return False

    client = p.connect(p.DIRECT)
    p.setGravity(0, 0, -9.81, physicsClientId=client)
    p.setTimeStep(time_step, physicsClientId=client)
    p.setAdditionalSearchPath(".", physicsClientId=client)

    # Map pybullet body id → (rb_doc_obj, linked_shape_obj, local_offset)
    body_map = {}

    try:
        for rb in rigid_bodies:
            linked = rb.LinkedObject
            shape = linked.Shape
            half = _bbox_half_extents(shape)
            center_m = _bbox_center_m(shape)

            col = p.createCollisionShape(
                p.GEOM_BOX, halfExtents=half, physicsClientId=client)

            pl = linked.Placement
            rot_q = pl.Rotation.Q          # (x, y, z, w) — FreeCAD quaternion

            is_active = (rb.BodyType == "Active")
            mass = rb.Mass if is_active else 0.0

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

            # Pre-compute local offset: placement origin → bbox center in local space
            world_center = FreeCAD.Vector(*[c * M_TO_MM for c in center_m])
            local_offset = pl.Rotation.inverted().multVec(world_center - pl.Base)

            body_map[body_id] = (rb, linked, local_offset)

        # --- simulation loop ---
        for step in range(steps):
            p.stepSimulation(physicsClientId=client)

            for body_id, (rb, linked, local_offset) in body_map.items():
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
                linked.Placement = FreeCAD.Placement(new_base, new_rot)

            if step % 6 == 0:
                FreeCADGui.updateGui()

            if callback:
                callback(step + 1, steps)

        FreeCAD.ActiveDocument.recompute()
        return True

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
        "The pybullet library is required to run the simulation.\n\n"
        "Install it with:\n\n"
        "  CFLAGS='-Wno-error=return-type' \\\n"
        "  CXXFLAGS='-Wno-error=return-type' \\\n"
        "  python3 -m pip install pybullet --break-system-packages\n\n"
        "(On openSUSE, first: sudo zypper install python313-devel)",
    )
