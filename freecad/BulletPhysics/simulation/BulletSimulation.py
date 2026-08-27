import FreeCAD
import math
import random
import time

MM_TO_M = 0.001
M_TO_MM = 1000.0
_last_stop_reason = ""
_last_compute_time_seconds = 0.0
_playback_body_types = {}


class SimulationFrame(dict):
    """Recorded placements plus the rigid-body state needed for playback."""

    def __init__(self, *args, passive_link_names=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.passive_link_names = tuple(passive_link_names)


def _report_event(message):
    """Write optional particle lifecycle events to FreeCAD's Report View."""
    from ..preferences.BulletPreferences import get_event_reporting_enabled
    if get_event_reporting_enabled():
        FreeCAD.Console.PrintMessage(f"BulletPhysics: {message}\n")


# ---------------------------------------------------------------------------
# Document-object helpers
# ---------------------------------------------------------------------------

def collect_rigid_bodies(doc=None, enabled_only=True):
    """Return valid rigid bodies, optionally excluding disabled bodies."""
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
                and hasattr(obj.OriginalObject, "Shape")
                and (not enabled_only or getattr(obj, "Enabled", True))):
            result.append(obj)
    return result


def _find_mesh_settings(doc=None):
    if doc is None:
        doc = FreeCAD.ActiveDocument
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "MeshSettingsFeature"):
            return obj
    return None


def _mesh_settings_error(rigid_bodies, emitters, observers=(), doc=None):
    """Return a preflight error for the shared rigid-body mesh, if any."""
    settings = _find_mesh_settings(doc)
    if settings is None:
        return "No global Mesh object found. Use Mesh Rigid Bodies and generate meshes first."
    if (getattr(settings, "GeneratedMesher", "") != settings.Mesher
            or abs(getattr(settings, "GeneratedMeshSize", 0.0) - settings.MeshSize) > 1e-9
            or abs(getattr(settings, "GeneratedAngularDeflection", 0.0)
                   - settings.AngularDeflection) > 1e-9):
        return "Mesh settings changed. Generate meshes again before simulating."

    sources = set()
    for mesh_obj in getattr(settings, "GeneratedMeshes", []):
        if mesh_obj is None or not hasattr(mesh_obj, "SourceObject"):
            continue
        try:
            if mesh_obj.Mesh.CountFacets > 0:
                sources.add(mesh_obj.SourceObject.Name)
                from ..objects.BulletMesh import source_shape_signature
                if (not hasattr(mesh_obj, "SourceShapeSignature")
                        or mesh_obj.SourceShapeSignature
                        != source_shape_signature(mesh_obj.SourceObject.Shape)):
                    return ("Collision mesh for '{}' is stale. "
                            "Generate meshes again before simulating."
                            .format(mesh_obj.SourceObject.Label))
        except Exception:
            pass
    source_objects = [body.OriginalObject for body in rigid_bodies]
    source_objects.extend(template for emitter in emitters
                          for template, _ratio in emitter_template_entries(emitter))
    source_objects.extend(observer.SourceObject for observer in observers)
    missing = [source.Label for source in source_objects if source.Name not in sources]
    if missing:
        return "Missing generated meshes for: " + ", ".join(missing)
    return ""


def _generated_mesh_for_source(settings, source):
    """Return the pre-generated mesh assigned to *source*, if available."""
    if settings is None:
        return None
    for mesh_obj in getattr(settings, "GeneratedMeshes", []):
        if getattr(mesh_obj, "SourceObject", None) == source:
            return mesh_obj.Mesh
    return None


def collect_launchers(doc=None):
    """Return launchers whose target body is enabled for simulation."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    result = []
    for obj in doc.Objects:
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletLauncherFeature"
                and hasattr(obj, "TargetBody")
                and obj.TargetBody is not None
                and getattr(obj.TargetBody, "Enabled", True)):
            result.append(obj)
    return result


def collect_emitters(doc=None, enabled_only=True):
    """Return valid emitters, optionally excluding disabled emitters."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    result = []
    for obj in doc.Objects:
        source = getattr(obj, "EmissionSource", None)
        templates = [template for template, _ratio in emitter_template_entries(obj)]
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletEmitterFeature"
                and (not enabled_only or getattr(obj, "Enabled", True))
                and source is not None
                and templates
                and hasattr(source, "Shape")
                and source.Shape is not None
                and all(hasattr(template, "Shape") and template.Shape is not None
                        for template in templates)):
            result.append(obj)
    return result


def emitter_template_entries(emitter):
    """Return (template, percentage) pairs, including old single-template emitters."""
    templates = [template for template in getattr(emitter, "TemplateObjects", [])
                 if template is not None]
    if not templates:
        template = getattr(emitter, "TemplateObject", None)
        templates = [template] if template is not None else []
    ratios = list(getattr(emitter, "TemplateRatios", []))
    if len(ratios) != len(templates):
        ratios = [100.0] if len(templates) == 1 else [0.0] * len(templates)
    return list(zip(templates, ratios))


def _emitter_template_ratio_error(emitters):
    for emitter in emitters:
        entries = emitter_template_entries(emitter)
        total = sum(max(0.0, ratio) for _template, ratio in entries)
        if not entries or abs(total - 100.0) > 1e-6:
            return (f"Emission ratios for '{emitter.Label}' must total 100%."
                    " Edit the emitter and set the percentage for each object.")
    return ""


def _all_emitters(doc=None):
    """Return every emitter feature, including incomplete or disabled ones."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    return [obj for obj in doc.Objects
            if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletEmitterFeature")]


def collect_destroy_bodies(doc=None):
    """Return enabled destruction triggers with a valid source shape."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    result = []
    for obj in doc.Objects:
        source = getattr(obj, "SourceObject", None)
        if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "DestroyRigidBodyFeature"
                and getattr(obj, "Enabled", True)
                and source is not None
                and hasattr(source, "Shape")
                and source.Shape is not None):
            result.append(obj)
    return result


def collect_observers(doc=None, enabled_only=True):
    """Return observer features with a valid volume or surface source."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    return [obj for obj in doc.Objects
            if (hasattr(obj, "Proxy")
                and type(obj.Proxy).__name__ == "BulletObserverFeature"
                and (not enabled_only or getattr(obj, "Enabled", True))
                and getattr(obj, "SourceObject", None) is not None
                and hasattr(obj.SourceObject, "Shape")
                and obj.SourceObject.Shape is not None)]


def _emitter_links(doc):
    links = []
    for emitter in _all_emitters(doc):
        links.extend(link for link in getattr(emitter, "GeneratedLinks", [])
                     if link is not None)
    return links


def _clear_emitter_links(doc, emitters):
    for emitter in emitters:
        for link in list(getattr(emitter, "GeneratedLinks", [])):
            if link is not None:
                doc.removeObject(link.Name)
        emitter.GeneratedLinks = []
    doc.recompute()


def _emitter_template_selector(entries):
    """Return a lazy, deterministic template selector for an emitter."""
    if len(entries) == 1:
        template = entries[0][0]
        return lambda: template

    # Smooth weighted round-robin spreads templates uniformly without storing
    # a sequence for every possible emission.
    weighted = [(template, int(round(max(0.0, ratio) * 1000)))
                for template, ratio in entries]
    total_weight = sum(weight for _template, weight in weighted)
    current_weights = [0] * len(weighted)

    def next_template():
        for index, (_template, weight) in enumerate(weighted):
            current_weights[index] += weight
        selected = max(range(len(weighted)), key=current_weights.__getitem__)
        current_weights[selected] -= total_weight
        return weighted[selected][0]

    return next_template


def _sample_emission_point(shape, rng):
    """Return a random world-space point in a solid, or on a surface shape."""
    bb = shape.BoundBox
    if getattr(shape, "Volume", 0.0) > 1e-9:
        for _ in range(128):
            point = FreeCAD.Vector(
                rng.uniform(bb.XMin, bb.XMax),
                rng.uniform(bb.YMin, bb.YMax),
                rng.uniform(bb.ZMin, bb.ZMax),
            )
            try:
                if shape.isInside(point, 1e-7, True):
                    return point
            except Exception:
                break

    try:
        vertices, triangles = shape.tessellate(1.0)
        weighted = []
        total_area = 0.0
        for triangle in triangles:
            a, b, c = (vertices[index] for index in triangle)
            area = (b - a).cross(c - a).Length * 0.5
            if area > 1e-12:
                total_area += area
                weighted.append((total_area, a, b, c))
        if weighted:
            target = rng.uniform(0.0, total_area)
            _, a, b, c = next(entry for entry in weighted if entry[0] >= target)
            u = rng.random()
            v = rng.random()
            if u + v > 1.0:
                u, v = 1.0 - u, 1.0 - v
            return a + (b - a) * u + (c - a) * v
    except Exception:
        pass

    return FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)


def _emitter_rotation(emitter, rng):
    orientation = getattr(emitter, "Orientation", FreeCAD.Vector())
    randomness = getattr(emitter, "OrientationRandomness", FreeCAD.Vector())
    variation = [max(0.0, min(1.0, value)) * 180.0
                 for value in (randomness.x, randomness.y, randomness.z)]
    return FreeCAD.Rotation(
        orientation.x + rng.uniform(-variation[0], variation[0]),
        orientation.y + rng.uniform(-variation[1], variation[1]),
        orientation.z + rng.uniform(-variation[2], variation[2]),
    )


def _emitter_direction(emitter, rng):
    direction = getattr(emitter, "Direction", FreeCAD.Vector(0, 0, 1))
    randomness = getattr(emitter, "DirectionRandomness", FreeCAD.Vector())
    return FreeCAD.Vector(
        direction.x + rng.uniform(-max(0.0, min(1.0, randomness.x)),
                                max(0.0, min(1.0, randomness.x))),
        direction.y + rng.uniform(-max(0.0, min(1.0, randomness.y)),
                                max(0.0, min(1.0, randomness.y))),
        direction.z + rng.uniform(-max(0.0, min(1.0, randomness.z)),
                                max(0.0, min(1.0, randomness.z))),
    )


def _emitter_schedule(emitters, time_step):
    schedule = {}
    for emitter in emitters:
        count = max(1, int(getattr(emitter, "Count", 1)))
        start = max(0.0, getattr(emitter, "StartTime", 0.0))
        end = max(start, getattr(emitter, "EndTime", start))
        for index in range(count):
            time = start if count == 1 else start + (end - start) * index / (count - 1)
            schedule.setdefault(max(0, int(round(time / time_step))), []).append(
                (emitter, index))
    return schedule


def apply_frame(frame, doc=None):
    """
    Apply one recorded frame to the active document.

    *frame* maps App::Link object Name → FreeCAD.Placement.
    Only Link objects are updated; originals are never touched.
    """
    import FreeCADGui
    if doc is None:
        doc = FreeCAD.ActiveDocument
    rigid_links = [rb.BodyLink for rb in collect_rigid_bodies(doc, enabled_only=False)
                   if rb.BodyLink is not None]
    emitted_links = _emitter_links(doc)
    playback_links = rigid_links + emitted_links
    playback_names = {link.Name for link in playback_links}
    passive_link_names = set(getattr(frame, "passive_link_names", ()))
    from ..preferences.BulletPreferences import apply_body_color
    for link in playback_links:
        if link.Name not in frame:
            link.ViewObject.Visibility = False
            continue
        body_type = "Passive" if link.Name in passive_link_names else "Active"
        playback_key = (doc.Name, link.Name)
        if _playback_body_types.get(playback_key) != body_type:
            apply_body_color(link, body_type)
            _playback_body_types[playback_key] = body_type
    for link_name, placement in frame.items():
        obj = doc.getObject(link_name)
        if obj is not None:
            obj.Placement = placement
            if link_name in playback_names:
                obj.ViewObject.Visibility = True
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
    Return [hx, hy, hz] in mm — collision half-extents in the body's local frame.

    Uses transformGeometry (not vertex iteration) so that analytic surfaces with
    very few BRep vertices give correct results:
      - Sphere: only 2 pole vertices → vertex scan gives [0, 0, R]; AABB of the
        un-rotated geometry gives [R, R, R]. ✓
      - Cylinder: only 2 seam vertices → similar issue fixed the same way. ✓
      - Box / mesh: vertex scan would also work, but this path is simpler.
    """
    mat = FreeCAD.Placement(FreeCAD.Vector(), orig_pl.Rotation.inverted()).toMatrix()
    try:
        bb = fc_shape.transformGeometry(mat).BoundBox
    except Exception:
        bb = fc_shape.BoundBox
    return [bb.XLength / 2.0, bb.YLength / 2.0, bb.ZLength / 2.0]


def _write_obj(verts_m, indices_flat, filepath):
    """Write a triangle mesh (metres) as a Wavefront OBJ file for VHACD input."""
    with open(filepath, "w") as f:
        for v in verts_m:
            f.write(f"v {v[0]:.8f} {v[1]:.8f} {v[2]:.8f}\n")
        for i in range(0, len(indices_flat), 3):
            f.write(f"f {indices_flat[i]+1} {indices_flat[i+1]+1} {indices_flat[i+2]+1}\n")


def _parse_vhacd_obj(filepath):
    """
    Parse a V-HACD output OBJ file.
    Returns a list of vertex lists, one list per convex hull.
    Vertices are in the same coordinate space as the input (metres).
    """
    hulls, current = [], []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line.startswith(("o ", "g ")):
                if current:
                    hulls.append(current)
                current = []
            elif line.startswith("v ") and not line.startswith(("vn ", "vt ")):
                parts = line.split()
                current.append([float(parts[1]), float(parts[2]), float(parts[3])])
    if current:
        hulls.append(current)
    return hulls


def _make_vhacd_compound_shape(p, verts_m, indices_flat, client, collision_margin=0.001):
    """
    Decompose a concave mesh into convex hulls via V-HACD and return a pybullet
    GEOM_COMPOUND collision shape valid for dynamic bodies.

    V-HACD is bundled with pybullet.  The mesh is written to a temporary OBJ,
    decomposed, then the resulting convex hulls are combined into one compound
    shape.  Returns None if V-HACD is unavailable or fails.
    """
    import tempfile, os

    if not hasattr(p, "vhacd"):
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: pybullet.vhacd not available — "
            "falling back to convex hull for dynamic mesh body.\n"
        )
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        obj_in  = os.path.join(tmpdir, "in.obj")
        obj_out = os.path.join(tmpdir, "out.obj")
        log_out = os.path.join(tmpdir, "vhacd.log")

        _write_obj(verts_m, indices_flat, obj_in)

        try:
            p.vhacd(obj_in, obj_out, log_out, physicsClientId=client)
        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                f"BulletPhysics: V-HACD decomposition failed ({exc})\n"
            )
            return None

        if not os.path.exists(obj_out):
            FreeCAD.Console.PrintWarning(
                "BulletPhysics: V-HACD produced no output file.\n"
            )
            return None

        hull_verts_list = _parse_vhacd_obj(obj_out)

    if not hull_verts_list:
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: V-HACD output contained no convex hulls.\n"
        )
        return None

    child_shapes = [
        p.createCollisionShape(p.GEOM_MESH, vertices=hv,
                               physicsClientId=client)
        for hv in hull_verts_list
    ]
    n = len(child_shapes)

    compound = p.createCollisionShape(
        p.GEOM_COMPOUND,
        children=child_shapes,
        childPositions=[[0.0, 0.0, 0.0]] * n,
        childOrientations=[[0.0, 0.0, 0.0, 1.0]] * n,
        physicsClientId=client,
    )

    FreeCAD.Console.PrintMessage(
        f"BulletPhysics: V-HACD → {n} convex hull(s) compound shape "
        f"for dynamic concave mesh\n"
    )
    return compound


def _tessellate_to_local(fc_shape, orig_pl, world_center, precision,
                         source_mesh=None):
    """
    Tessellate fc_shape and return (vertices, flat_indices) in body-local space.

    Body-local space is centred at world_center (the bbox centre) and has the
    same orientation as orig_pl.  Coordinates are in metres.

    *precision* is the maximum chord deviation in mm (from MeshResolution).
    """
    if source_mesh is not None:
        verts_world, tri_faces = source_mesh.Topology
    else:
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
                          client, is_static=False, mesh_resolution=1.0,
                          forced_type=None, collision_margin=0.001,
                          source_mesh=None):
    """
    Create the most accurate pybullet collision shape for fc_shape.

    For recognised primitives (sphere, cylinder, box) the exact analytic shape
    is used.  For any other solid a mesh is tessellated from the FreeCAD shape:
      - 'mesh' / static auto: btBvhTriangleMeshShape — exact concave, static only
      - 'convex_hull' / dynamic auto: btConvexHullShape — convex approx, dynamic-safe

    *forced_type* overrides auto-detection: 'box', 'sphere', 'cylinder',
    'convex_hull', or 'mesh'.

    Returns (collision_shape_id, characteristic_radius_m).
    """
    shape_type = forced_type or _detect_freecad_shape_type(fc_shape)
    hx, hy, hz = half_extents

    if shape_type == "sphere":
        try:
            # Read the analytic radius directly — BoundBox can over-estimate
            # due to OCCT approximation of curved surfaces.
            radius = fc_shape.Faces[0].Surface.Radius * MM_TO_M
        except Exception:
            radius = (hx + hy + hz) / 3.0
        col = p.createCollisionShape(
            p.GEOM_SPHERE, radius=radius, physicsClientId=client)
        return col, radius

    if shape_type == "cylinder":
        try:
            cyl_face  = next((f for f in fc_shape.Faces
                              if "Cylinder" in type(f.Surface).__name__), None)
            seam_edge = next((e for e in fc_shape.Edges
                              if "Line" in type(e.Curve).__name__), None)
            if cyl_face is None or seam_edge is None:
                raise ValueError("cylinder geometry not found")
            radius = cyl_face.Surface.Radius * MM_TO_M
            height = seam_edge.Length * MM_TO_M
        except Exception:
            half_sorted = sorted([hx, hy, hz])
            radius = (half_sorted[0] + half_sorted[1]) / 2.0
            height = half_sorted[2] * 2.0
        col = p.createCollisionShape(
            p.GEOM_CYLINDER,
            radius=radius,
            height=height,
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
            fc_shape, orig_pl, world_center, mesh_resolution, source_mesh)

        # Determine mesh mode:
        #   forced "mesh"       → always concave BVH (btBvhTriangleMeshShape)
        #   forced "convex_hull"→ always convex hull (btConvexHullShape)
        #   Auto                → concave BVH for static, convex hull for dynamic
        if forced_type == "mesh":
            use_concave = True
        elif forced_type == "convex_hull":
            use_concave = False
        else:
            use_concave = is_static

        if use_concave and is_static:
            # Static body: exact concave BVH triangle mesh.
            col = p.createCollisionShape(
                p.GEOM_MESH,
                vertices=verts,
                indices=indices,
                flags=p.GEOM_CONCAVE_INTERNAL_EDGE,
                physicsClientId=client,
            )
            FreeCAD.Console.PrintMessage(
                f"BulletPhysics: concave mesh ({len(verts)} verts, "
                f"{len(indices)//3} tris, res={mesh_resolution} mm) for static body\n"
            )
        elif use_concave:
            # Dynamic body with concave mesh: decompose into convex hulls via
            # V-HACD so Bullet can compute correct collision response and rotation.
            col = _make_vhacd_compound_shape(p, verts, indices, client, collision_margin)
            if col is None:
                # V-HACD unavailable or failed: fall back to single convex hull.
                col = p.createCollisionShape(
                    p.GEOM_MESH,
                    vertices=verts,
                    physicsClientId=client,
                )
                FreeCAD.Console.PrintMessage(
                    f"BulletPhysics: convex hull fallback ({len(verts)} verts, "
                    f"res={mesh_resolution} mm) after V-HACD failure\n"
                )
        else:
            # convex_hull forced or auto for dynamic body.
            col = p.createCollisionShape(
                p.GEOM_MESH,
                vertices=verts,
                physicsClientId=client,
            )
            FreeCAD.Console.PrintMessage(
                f"BulletPhysics: convex hull ({len(verts)} verts, "
                f"res={mesh_resolution} mm) for custom shape\n"
            )
        return col, min(half_extents)

    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            f"BulletPhysics: mesh failed ({exc}), falling back to bounding box\n"
        )
        col = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=half_extents, physicsClientId=client)
        return col, min(half_extents)


def _delete_rigid_body_definition(doc, rigid_body):
    """Delete a rigid-body wrapper and its link, preserving the CAD source object."""
    from ..objects.BulletContainer import find_container

    container = find_container(doc)
    if container is not None and hasattr(container, "RigidBodies"):
        container.RigidBodies = [rb for rb in container.RigidBodies
                                 if rb != rigid_body]

    launchers = [obj for obj in doc.Objects
                 if (hasattr(obj, "Proxy")
                     and type(obj.Proxy).__name__ == "BulletLauncherFeature"
                     and getattr(obj, "TargetBody", None) == rigid_body)]
    if container is not None and hasattr(container, "Launchers"):
        container.Launchers = [launcher for launcher in container.Launchers
                               if launcher not in launchers]
    for launcher in launchers:
        doc.removeObject(launcher.Name)

    link = rigid_body.BodyLink
    doc.removeObject(rigid_body.Name)
    if link is not None:
        doc.removeObject(link.Name)
    doc.recompute()


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def get_last_stop_reason():
    """Return the reason the most recent simulation ended early, if any."""
    return _last_stop_reason


def get_last_compute_time_seconds():
    """Return the wall-clock duration of the most recent simulation run."""
    return _last_compute_time_seconds


def run_simulation(callback=None, stop_on_contact=None, stop_delay=0.0,
                   stop_body_type="Active"):
    """
    Run the Bullet Physics simulation using settings from the BulletWorld object.

    Returns (frames, time_step, speed_frames), or None on error.
    Each placement frame maps App::Link.Name to FreeCAD.Placement; each speed
    frame maps the same link names to scalar Bullet linear velocity in m/s.
    """
    global _last_stop_reason, _last_compute_time_seconds
    _last_stop_reason = ""
    _last_compute_time_seconds = 0.0
    _playback_body_types.clear()
    compute_started_at = time.perf_counter()
    stop_delay = max(0.0, float(stop_delay))

    try:
        import sys
        from ..preferences.BulletPreferences import get_pybullet_path
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

    from ..objects.BulletWorld import find_world

    rigid_bodies = collect_rigid_bodies()
    all_emitters = _all_emitters()
    emitters = collect_emitters(enabled_only=True)
    observers = collect_observers(enabled_only=True)
    if not rigid_bodies and not emitters:
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: No enabled rigid bodies or emitters found.\n"
            "Add Active/Passive rigid bodies or configure an emitter first.\n"
        )
        return None
    ratio_error = _emitter_template_ratio_error(emitters)
    if ratio_error:
        FreeCAD.Console.PrintWarning(f"BulletPhysics: {ratio_error}\n")
        return None
    mesh_settings = _find_mesh_settings()
    if mesh_settings is None:
        FreeCAD.Console.PrintWarning(
            "BulletPhysics: No global Mesh object found. Use Mesh Rigid Bodies first.\n")
        return None
    try:
        from ..objects.BulletMesh import generate_meshes
        generated_count = generate_meshes(mesh_settings)
        FreeCAD.Console.PrintMessage(
            f"BulletPhysics: regenerated {generated_count} global mesh(es).\n")
    except Exception as exc:
        FreeCAD.Console.PrintWarning(
            f"BulletPhysics: could not generate global meshes ({exc}).\n")
        return None
    mesh_error = _mesh_settings_error(rigid_bodies, emitters, observers)
    if mesh_error:
        FreeCAD.Console.PrintWarning(f"BulletPhysics: {mesh_error}\n")
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
        mesh_resolution  = 1.0
        collision_margin = max(0.0, getattr(world, "CollisionMargin", 0.001))
        linear_damping   = max(0.0, min(1.0, getattr(world, "LinearDamping", 0.0)))
        angular_damping  = max(0.0, min(1.0, getattr(world, "AngularDamping", 0.0)))
        stop_when_settled = getattr(world, "StopWhenSettled", False)
        settle_linear = max(0.0, getattr(world, "SettleLinearVelocity", 0.01))
        settle_angular = max(0.0, getattr(world, "SettleAngularVelocity", 0.01))
        settle_duration = max(0.0, getattr(world, "SettleDuration", 0.5))
    else:
        gravity_mag      = 9.81
        gravity_dir      = FreeCAD.Vector(0, 0, -1)
        end_time         = 10.0
        time_step        = 1.0 / 60.0
        solver_iters     = 10
        sub_steps        = 4
        mesh_resolution  = 1.0
        collision_margin = 0.001
        linear_damping   = 0.0
        angular_damping  = 0.0
        stop_when_settled = False
        settle_linear = 0.01
        settle_angular = 0.01
        settle_duration = 0.5

    if mesh_settings is not None:
        mesh_resolution = max(0.001, mesh_settings.MeshSize)

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

    _clear_emitter_links(FreeCAD.ActiveDocument, all_emitters)
    generated_emitter_links = {emitter.Name: [] for emitter in emitters}

    # {bullet_id: (body_config_obj, link_obj, local_offset_mm, is_emitted)}
    body_map = {}
    # Emitted active bodies scheduled to become static at a simulation time.
    passivate_at = {}
    passivated_body_ids = set()
    # {bullet_id: (fire_step, vel_x, vel_y, vel_z, actual_mass)}
    launch_map = {}
    # {bullet_id: DestroyRigidBodyFeature}
    destroy_trigger_ids = {}
    # {bullet_id: BulletObserverFeature}; observers never collide physically.
    observer_ids = {}
    observer_body_states = {}
    observer_match_started_at = {}
    # {bullet_id: (BulletEmitterFeature, "Start" | "Stop")}
    emitter_condition_trigger_ids = {}
    # [(observer_bullet_id, emitter, "Start" | "Stop", required_body_type)]
    emitter_observer_conditions = []
    stop_trigger_id = None
    stop_contact_started_at = None
    stop_contact_body = ""

    for trigger in collect_destroy_bodies():
        source = trigger.SourceObject
        shape = source.Shape
        source_pl = source.Placement
        bb = shape.BoundBox
        world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
        half = [value * MM_TO_M
                for value in _local_half_extents(shape, source_pl)]
        collision_shape, _ = _make_collision_shape(
            p, shape, half, source_pl, world_center, client,
            is_static=True, mesh_resolution=mesh_resolution,
            collision_margin=collision_margin)
        trigger_id = p.createMultiBody(
            baseMass=0.0,
            baseCollisionShapeIndex=collision_shape,
            basePosition=[world_center.x * MM_TO_M,
                          world_center.y * MM_TO_M,
                          world_center.z * MM_TO_M],
            baseOrientation=source_pl.Rotation.Q,
            physicsClientId=client,
        )
        destroy_trigger_ids[trigger_id] = trigger

    for observer in observers:
        source = observer.SourceObject
        shape = source.Shape
        source_pl = source.Placement
        bb = shape.BoundBox
        world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
        half = [value * MM_TO_M
                for value in _local_half_extents(shape, source_pl)]
        collision_shape, _ = _make_collision_shape(
            p, shape, half, source_pl, world_center, client,
            is_static=True, mesh_resolution=mesh_resolution,
            collision_margin=collision_margin,
            source_mesh=_generated_mesh_for_source(mesh_settings, source))
        observer_id = p.createMultiBody(
            baseMass=0.0,
            baseCollisionShapeIndex=collision_shape,
            basePosition=[world_center.x * MM_TO_M,
                          world_center.y * MM_TO_M,
                          world_center.z * MM_TO_M],
            baseOrientation=source_pl.Rotation.Q,
            physicsClientId=client,
        )
        # This body exists only for geometric queries. It must not create a
        # contact response or otherwise influence the simulation.
        p.setCollisionFilterGroupMask(
            observer_id, -1, 0, 0, physicsClientId=client)
        observer_ids[observer_id] = observer
        observer_body_states[observer_id] = {}
        observer_match_started_at[observer_id] = {}
        observer.CurrentBodies = []
        observer.LastEvent = ""
        observer.Triggered = False
        observer.TriggerBody = ""
        observer.TriggerTime = 0.0

    def emitter_condition_type(emitter, name, source):
        """Return the selected condition mode, including pre-mode documents."""
        default = "Collision Object" if source is not None else "Time"
        return getattr(emitter, f"{name}ConditionType", default)

    def condition_body_type(obj, name):
        property_prefix = "Stop" if name == "End" else name
        return getattr(obj, f"{property_prefix}ConditionBodyType", "Active")

    for emitter in emitters:
        for condition_type, source in (
                ("Start", getattr(emitter, "StartConditionObject", None)),
                ("End", getattr(emitter, "StopConditionObject", None))):
            if emitter_condition_type(emitter, condition_type, source) != "Collision Object":
                continue
            if source is None or not hasattr(source, "Shape") or source.Shape is None:
                continue
            shape = source.Shape
            source_pl = source.Placement
            bb = shape.BoundBox
            world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
            half = [value * MM_TO_M
                    for value in _local_half_extents(shape, source_pl)]
            collision_shape, _ = _make_collision_shape(
                p, shape, half, source_pl, world_center, client,
                is_static=True, mesh_resolution=mesh_resolution,
                collision_margin=collision_margin)
            trigger_id = p.createMultiBody(
                baseMass=0.0,
                baseCollisionShapeIndex=collision_shape,
                basePosition=[world_center.x * MM_TO_M,
                              world_center.y * MM_TO_M,
                              world_center.z * MM_TO_M],
                baseOrientation=source_pl.Rotation.Q,
                physicsClientId=client,
            )
            emitter_condition_trigger_ids[trigger_id] = (
                emitter, condition_type, condition_body_type(emitter, condition_type))

        for condition_type, observer in (
                ("Start", getattr(emitter, "StartConditionObserver", None)),
                ("End", getattr(emitter, "StopConditionObserver", None))):
            if emitter_condition_type(emitter, condition_type, observer) != "Observer":
                continue
            for observer_id, configured_observer in observer_ids.items():
                if configured_observer == observer:
                    emitter_observer_conditions.append(
                        (observer_id, emitter, condition_type,
                         condition_body_type(emitter, condition_type)))
                    break

    stop_observer = (stop_on_contact if hasattr(stop_on_contact, "Proxy")
                     and type(stop_on_contact.Proxy).__name__ == "BulletObserverFeature"
                     else None)
    if (stop_on_contact is not None and stop_observer is None
            and hasattr(stop_on_contact, "Shape")
            and stop_on_contact.Shape is not None):
        shape = stop_on_contact.Shape
        source_pl = stop_on_contact.Placement
        bb = shape.BoundBox
        world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
        half = [value * MM_TO_M
                for value in _local_half_extents(shape, source_pl)]
        collision_shape, _ = _make_collision_shape(
            p, shape, half, source_pl, world_center, client,
            is_static=True, mesh_resolution=mesh_resolution,
            collision_margin=collision_margin)
        stop_trigger_id = p.createMultiBody(
            baseMass=0.0,
            baseCollisionShapeIndex=collision_shape,
            basePosition=[world_center.x * MM_TO_M,
                          world_center.y * MM_TO_M,
                          world_center.z * MM_TO_M],
            baseOrientation=source_pl.Rotation.Q,
            physicsClientId=client,
        )

    emitter_configs = {}
    emitter_rngs = {}

    for emitter in emitters:
        seed = max(0, int(getattr(emitter, "RandomSeed", 0)))
        direction_seed = max(0, int(getattr(emitter, "DirectionRandomSeed", 0)))
        emitter_rngs[emitter.Name] = (
            random.Random(seed if seed else None),
            random.Random(direction_seed if direction_seed else None),
        )
        configs = {}
        is_static = emitter.BodyType == "Passive"
        density = max(0.0, getattr(emitter, "Density", 1000.0))
        for template, _ratio in emitter_template_entries(emitter):
            template_shape = template.Shape
            template_pl = template.Placement
            bb = template_shape.BoundBox
            template_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
            half_mm = _local_half_extents(template_shape, template_pl)
            half = [value * MM_TO_M for value in half_mm]
            col, characteristic_radius = _make_collision_shape(
                p, template_shape, half, template_pl, template_center, client,
                is_static=is_static, mesh_resolution=mesh_resolution,
                collision_margin=collision_margin,
                source_mesh=_generated_mesh_for_source(mesh_settings, template))
            local_offset = template_pl.Rotation.inverted().multVec(
                template_center - template_pl.Base)
            mass = 0.0 if is_static else density * template_shape.Volume * 1e-9
            configs[template.Name] = (
                col, characteristic_radius, mass, local_offset,
                max(0.0, getattr(emitter, "Restitution", 0.3)),
                max(0.0, getattr(emitter, "Friction", 0.5)),
            )
        emitter_configs[emitter.Name] = configs

    emitter_schedules = {}
    started_emitters = set()
    stopped_emitters = set()

    def schedule_emitter(emitter, base_step):
        """Store an emitter's schedule without allocating future particles."""
        start = max(0.0, getattr(emitter, "StartTime", 0.0))
        end = max(0.0, getattr(emitter, "EndTime", 0.0))
        start_step = base_step + max(0, int(round(start / time_step)))
        last_step = max(0, steps - 1)
        # An end time of zero is an open emission window.  Its configured
        # count is distributed through the remaining simulation frames; only
        # simulation completion or an end collision can stop it earlier.
        if end <= 0.0:
            end_step = last_step
        else:
            end = max(start, end)
            end_step = base_step + max(0, int(round(end / time_step)))
        end_step = max(start_step, min(last_step, end_step))
        if getattr(emitter, "UseParticlesPerSecond", False):
            rate = max(0.001, getattr(emitter, "ParticlesPerSecond", 1.0))
            duration = max(0.0, (end_step - start_step) * time_step)
            count = max(1, int(math.ceil(rate * duration)))
        else:
            count = max(1, int(getattr(emitter, "Count", 1)))
        emitter_schedules[emitter.Name] = {
            "emitter": emitter,
            "start_step": start_step,
            "end_step": end_step,
            "count": count,
            "next_index": 0,
            "rate": rate if getattr(emitter, "UseParticlesPerSecond", False) else None,
            "next_template": _emitter_template_selector(
                emitter_template_entries(emitter)),
        }

    def scheduled_emission_step(schedule, index):
        if schedule["rate"] is not None:
            return (schedule["start_step"]
                    + int(round(index / (schedule["rate"] * time_step))))
        if schedule["count"] == 1:
            return schedule["start_step"]
        return (schedule["start_step"]
                + (schedule["end_step"] - schedule["start_step"])
                * index // (schedule["count"] - 1))

    def emit_scheduled_particles(step):
        """Materialize only the particles whose emission step has arrived."""
        for schedule in emitter_schedules.values():
            emitter = schedule["emitter"]
            if emitter.Name in stopped_emitters:
                continue
            while schedule["next_index"] < schedule["count"]:
                index = schedule["next_index"]
                scheduled_step = scheduled_emission_step(schedule, index)
                if scheduled_step > schedule["end_step"] or scheduled_step > step:
                    break
                spawn_emission(
                    emitter, index, schedule["next_template"](),
                    step * time_step)
                schedule["next_index"] += 1

    for emitter in emitters:
        start_source = getattr(emitter, "StartConditionObject", None)
        if emitter_condition_type(emitter, "Start", start_source) != "Collision Object":
            schedule_emitter(emitter, 0)
            started_emitters.add(emitter.Name)

    def spawn_emission(emitter, index, template, emission_time):
        rng, direction_rng = emitter_rngs[emitter.Name]
        (col, characteristic_radius, mass, local_offset,
         restitution, friction) = emitter_configs[emitter.Name][template.Name]
        link = FreeCAD.ActiveDocument.addObject(
            "App::Link", f"_BtEmit_{emitter.Name}_{index + 1}")
        link.setLink(template)
        link.Label = f"Emission {index + 1}: {template.Label}"
        from ..preferences.BulletPreferences import apply_body_color
        apply_body_color(link, emitter.BodyType)
        if FreeCAD.GuiUp:
            link.ViewObject.Visibility = False
        generated_emitter_links[emitter.Name].append(link)
        emitter.GeneratedLinks = generated_emitter_links[emitter.Name]
        center = _sample_emission_point(emitter.EmissionSource.Shape, rng)
        rotation = _emitter_rotation(emitter, rng)
        body_id = p.createMultiBody(
            baseMass=mass,
            baseCollisionShapeIndex=col,
            basePosition=[center.x * MM_TO_M, center.y * MM_TO_M, center.z * MM_TO_M],
            baseOrientation=rotation.Q,
            physicsClientId=client,
        )
        p.changeDynamics(
            body_id, -1,
            restitution=restitution,
            lateralFriction=friction,
            collisionMargin=collision_margin,
            physicsClientId=client,
        )
        if mass > 0:
            p.changeDynamics(
                body_id, -1,
                ccdSweptSphereRadius=characteristic_radius * 0.4,
                activationState=4,
                linearDamping=linear_damping,
                angularDamping=angular_damping,
                physicsClientId=client,
            )
            direction = _emitter_direction(emitter, direction_rng)
            length = (direction.x**2 + direction.y**2 + direction.z**2) ** 0.5
            if length > 1e-9:
                speed = max(0.0, getattr(emitter, "Velocity", 0.0))
                p.resetBaseVelocity(
                    body_id,
                    linearVelocity=[direction.x / length * speed,
                                    direction.y / length * speed,
                                    direction.z / length * speed],
                    physicsClientId=client,
                )
        base = center - rotation.multVec(local_offset)
        link.Placement = FreeCAD.Placement(base, rotation)
        if FreeCAD.GuiUp:
            link.ViewObject.Visibility = True
        body_map[body_id] = (emitter, link, local_offset, True)
        become_passive_after = max(
            0.0, getattr(emitter, "BecomePassiveAfter", 0.0))
        if mass > 0.0 and become_passive_after > 0.0:
            passivate_at[body_id] = emission_time + become_passive_after
        _report_event(
            f"particle '{link.Label}' emitted by '{emitter.Label}'.")

    def body_is_active(body_id, entry):
        """Return whether a body currently participates as an active body."""
        return (entry is not None
                and entry[0].BodyType == "Active"
                and body_id not in passivated_body_ids)

    def body_matches_type(body_id, entry, required_type):
        if entry is None:
            return False
        if required_type == "Any":
            return True
        current_type = "Active" if body_is_active(body_id, entry) else "Passive"
        return current_type == required_type

    def observer_body_details(body_id, entry):
        """Return the user-facing type and linear speed for one Bullet body."""
        linear, _angular = p.getBaseVelocity(body_id, physicsClientId=client)
        speed = sum(value * value for value in linear) ** 0.5
        body_type = "Active" if body_is_active(body_id, entry) else "Passive"
        return body_type, speed

    def observer_condition_matches(observer, body_type, speed):
        """Evaluate the observer-owned body-type and speed rules."""
        required_type = getattr(observer, "BodyTypeCondition", "Any")
        speed_mode = getattr(observer, "SpeedCondition", "Any")
        type_enabled = required_type != "Any"
        speed_enabled = speed_mode != "Any"
        type_match = body_type == required_type
        threshold = max(0.0, getattr(observer, "Speed", 0.0))
        speed_match = (speed >= threshold if speed_mode == "At least"
                       else speed <= threshold)
        enabled_matches = []
        if type_enabled:
            enabled_matches.append(type_match)
        if speed_enabled:
            enabled_matches.append(speed_match)
        if not enabled_matches:
            return True
        if getattr(observer, "ConditionLogic", "AND") == "OR":
            return any(enabled_matches)
        return all(enabled_matches)

    def body_touches_observer(observer_id, observer, body_id):
        """Check both volume containment and shape contact without response."""
        position, _orientation = p.getBasePositionAndOrientation(
            body_id, physicsClientId=client)
        point = FreeCAD.Vector(
            position[0] * M_TO_MM,
            position[1] * M_TO_MM,
            position[2] * M_TO_MM)
        try:
            if observer.SourceObject.Shape.isInside(point, 1e-7, True):
                return True
        except Exception:
            pass
        try:
            return bool(p.getClosestPoints(
                bodyA=observer_id, bodyB=body_id, distance=0.0,
                physicsClientId=client))
        except Exception:
            return False

    def update_observers(frame_number, current_time):
        """Report rigid bodies entering, leaving, or changing type in observers."""
        for observer_id, observer in observer_ids.items():
            previous = observer_body_states[observer_id]
            current = {}
            details = []
            matching = {}
            for body_id, entry in body_map.items():
                if not body_touches_observer(observer_id, observer, body_id):
                    continue
                body_type, speed = observer_body_details(body_id, entry)
                current[body_id] = body_type
                if observer_condition_matches(observer, body_type, speed):
                    matching[body_id] = (entry, body_type, speed)
                details.append("{}: {} ({:.6g} m/s)".format(
                    entry[1].Label, body_type, speed))
                if body_id not in previous:
                    message = ("observer '{}' frame {} (t={:.6f} s): '{}' entered "
                               "as {} at {:.6g} m/s".format(
                                   observer.Label, frame_number, current_time,
                                   entry[1].Label, body_type, speed))
                    observer.LastEvent = message
                    FreeCAD.Console.PrintMessage("BulletPhysics: {}\n".format(message))
                elif previous[body_id] != body_type:
                    message = ("observer '{}' frame {} (t={:.6f} s): '{}' changed "
                               "from {} to {} at {:.6g} m/s".format(
                                   observer.Label, frame_number, current_time,
                                   entry[1].Label, previous[body_id], body_type, speed))
                    observer.LastEvent = message
                    FreeCAD.Console.PrintMessage("BulletPhysics: {}\n".format(message))
            for body_id, old_type in previous.items():
                if body_id in current:
                    continue
                entry = body_map.get(body_id)
                label = entry[1].Label if entry is not None else "removed body"
                message = ("observer '{}' frame {} (t={:.6f} s): '{}' left "
                           "as {}".format(
                               observer.Label, frame_number, current_time,
                               label, old_type))
                observer.LastEvent = message
                FreeCAD.Console.PrintMessage("BulletPhysics: {}\n".format(message))
            if current != previous:
                observer.CurrentBodies = sorted(details)
            observer_body_states[observer_id] = current
            started_at = observer_match_started_at[observer_id]
            for body_id in list(started_at):
                if body_id not in matching:
                    del started_at[body_id]
            for body_id, (entry, body_type, speed) in matching.items():
                started_at.setdefault(body_id, current_time)
                if (not observer.Triggered
                        and current_time - started_at[body_id]
                        >= max(0.0, getattr(observer, "TriggerDelay", 0.0))):
                    observer.Triggered = True
                    observer.TriggerBody = entry[1].Label
                    observer.TriggerTime = current_time
                    message = ("observer '{}' triggered at frame {} (t={:.6f} s): "
                               "'{}' matched as {} at {:.6g} m/s".format(
                                   observer.Label, frame_number, current_time,
                                   entry[1].Label, body_type, speed))
                    observer.LastEvent = message
                    FreeCAD.Console.PrintMessage("BulletPhysics: {}\n".format(message))

    def matching_observer_body(observer_id, _required_type=None):
        """Return the latched observer signal body, if the observer triggered."""
        observer = observer_ids[observer_id]
        return observer.TriggerBody if observer.Triggered else ""

    def passivate_emitted_bodies(current_time, frame_number):
        """Freeze emitted active bodies whose configured lifetime has elapsed."""
        for body_id, passive_time in list(passivate_at.items()):
            if current_time < passive_time:
                continue
            entry = body_map.get(body_id)
            del passivate_at[body_id]
            if entry is None:
                continue
            p.changeDynamics(body_id, -1, mass=0.0, physicsClientId=client)
            p.resetBaseVelocity(
                body_id, linearVelocity=[0.0, 0.0, 0.0],
                angularVelocity=[0.0, 0.0, 0.0], physicsClientId=client)
            passivated_body_ids.add(body_id)
            from ..preferences.BulletPreferences import apply_body_color
            apply_body_color(entry[1], "Passive", refresh=True)
            FreeCAD.Console.PrintMessage(
                f"BulletPhysics: emitted particle '{entry[1].Label}' became "
                f"passive at frame {frame_number} (t={current_time:.6f} s).\n")

    def destroy_contacted_bodies():
        """Remove active bodies as soon as they contact a destruction trigger."""
        destroyed = {}
        for trigger_id, trigger in destroy_trigger_ids.items():
            contacts = p.getContactPoints(bodyA=trigger_id, physicsClientId=client)
            for contact in contacts:
                body_id = contact[2]
                entry = body_map.get(body_id)
                if body_is_active(body_id, entry):
                    destroyed[body_id] = trigger

        for body_id, trigger in destroyed.items():
            body_config, link, _local_offset, is_emitted = body_map.pop(body_id)
            body_label = body_config.Label
            launch_map.pop(body_id, None)
            passivate_at.pop(body_id, None)
            passivated_body_ids.discard(body_id)
            p.removeBody(body_id, physicsClientId=client)

            if is_emitted:
                if FreeCAD.GuiUp:
                    link.ViewObject.Visibility = False
            elif trigger.Action == "Delete":
                _delete_rigid_body_definition(FreeCAD.ActiveDocument, body_config)
            else:
                body_config.Enabled = False
                if FreeCAD.GuiUp:
                    link.ViewObject.Visibility = False

            _report_event(
                f"particle '{body_label}' {trigger.Action.lower()}d by "
                f"destroy trigger '{trigger.Label}'.")

    def conditional_stop_contact():
        """Return the body label satisfying the configured stop condition."""
        if stop_observer is not None:
            for observer_id, observer in observer_ids.items():
                if observer == stop_observer:
                    return matching_observer_body(observer_id, stop_body_type)
        if stop_trigger_id is None:
            return ""
        contacts = p.getContactPoints(bodyA=stop_trigger_id, physicsClientId=client)
        for contact in contacts:
            entry = body_map.get(contact[2])
            if body_matches_type(contact[2], entry, stop_body_type):
                return entry[0].Label
        return ""

    def update_emitter_conditions(next_step, event_time):
        """Start or stop emitters whose configured trigger was just touched."""
        for trigger_id, (emitter, condition_type, required_type) in emitter_condition_trigger_ids.items():
            contacts = p.getContactPoints(bodyA=trigger_id, physicsClientId=client)
            touched = any(
                body_matches_type(contact[2], body_map.get(contact[2]), required_type)
                for contact in contacts)
            if not touched:
                continue
            if condition_type == "Start" and emitter.Name not in started_emitters:
                if emitter.Name not in stopped_emitters:
                    schedule_emitter(emitter, next_step)
                    FreeCAD.Console.PrintMessage(
                        f"BulletPhysics: emitter '{emitter.Label}' start "
                        f"condition triggered at frame {next_step} "
                        f"(t={event_time:.6f} s) by target "
                        f"'{emitter.StartConditionObject.Label}'.\n")
                started_emitters.add(emitter.Name)
            elif condition_type == "End" and emitter.Name not in stopped_emitters:
                stopped_emitters.add(emitter.Name)
                FreeCAD.Console.PrintMessage(
                    f"BulletPhysics: emitter '{emitter.Label}' stop "
                    f"condition triggered at frame {next_step} "
                    f"(t={event_time:.6f} s) by target "
                    f"'{emitter.StopConditionObject.Label}'.\n")

        for observer_id, emitter, condition_type, required_type in emitter_observer_conditions:
            body_label = matching_observer_body(observer_id, required_type)
            if not body_label:
                continue
            observer = observer_ids[observer_id]
            if condition_type == "Start" and emitter.Name not in started_emitters:
                if emitter.Name not in stopped_emitters:
                    schedule_emitter(emitter, next_step)
                    FreeCAD.Console.PrintMessage(
                        f"BulletPhysics: emitter '{emitter.Label}' start observer "
                        f"condition triggered at frame {next_step} "
                        f"(t={event_time:.6f} s): '{body_label}' is "
                        f"{required_type.lower()} in '{observer.Label}'.\n")
                started_emitters.add(emitter.Name)
            elif condition_type == "End" and emitter.Name not in stopped_emitters:
                stopped_emitters.add(emitter.Name)
                FreeCAD.Console.PrintMessage(
                    f"BulletPhysics: emitter '{emitter.Label}' stop observer "
                    f"condition triggered at frame {next_step} "
                    f"(t={event_time:.6f} s): '{body_label}' is "
                    f"{required_type.lower()} in '{observer.Label}'.\n")

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
            from ..preferences.BulletPreferences import apply_body_color
            apply_body_color(link, rb.BodyType)

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
            effective_res = mesh_resolution
            override = getattr(rb, "ShapeOverride", "Auto")
            forced_type = None if override == "Auto" else override
            col, characteristic_radius = _make_collision_shape(
                p, shape, half, orig_pl, world_center, client,
                is_static=is_static, mesh_resolution=effective_res,
                forced_type=forced_type, collision_margin=collision_margin,
                source_mesh=_generated_mesh_for_source(mesh_settings, original))

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
                collisionMargin=collision_margin,
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

            body_map[body_id] = (rb, link, local_offset, False)

        emit_scheduled_particles(0)

        # Frame 0 — initial placements of all Links (before any stepping)
        initial_frame = SimulationFrame()
        initial_speeds = {}
        for body_id, (rb, link, _, _) in body_map.items():
            initial_frame[link.Name] = link.Placement.copy()
            if rb.BodyType == "Active":
                linear, _angular = p.getBaseVelocity(
                    body_id, physicsClientId=client)
                initial_speeds[link.Name] = sum(value * value for value in linear) ** 0.5
            else:
                initial_speeds[link.Name] = 0.0
        initial_frame.passive_link_names = tuple(
            link.Name for body_id, (_rb, link, _offset, _emitted) in body_map.items()
            if not body_is_active(body_id, body_map.get(body_id)))
        frames = [initial_frame]
        speed_frames = [initial_speeds]

        fired_launchers = set()
        settled_elapsed = 0.0

        def has_future_simulation_events(current_step):
            """Keep settling disabled until queued launches/emissions are complete."""
            if any(body_id not in fired_launchers and fire_step > current_step
                   for body_id, (fire_step, *_values) in launch_map.items()):
                return True
            return any(
                schedule["emitter"].Name not in stopped_emitters
                and schedule["next_index"] < schedule["count"]
                and scheduled_emission_step(schedule, schedule["next_index"])
                > current_step
                for schedule in emitter_schedules.values())

        def active_bodies_settled(current_step):
            if has_future_simulation_events(current_step):
                return False
            for body_id, (body_config, _link, _offset, _emitted) in body_map.items():
                if not body_is_active(body_id, body_map.get(body_id)):
                    continue
                linear, angular = p.getBaseVelocity(
                    body_id, physicsClientId=client)
                linear_speed = sum(value * value for value in linear) ** 0.5
                angular_speed = sum(value * value for value in angular) ** 0.5
                if linear_speed > settle_linear or angular_speed > settle_angular:
                    return False
            return True

        # Simulation loop — each recorded frame runs sub_steps Bullet ticks
        for step in range(steps):
            conditional_stop_reason = ""
            if step > 0:
                emit_scheduled_particles(step)

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

            for sub_step in range(sub_steps):
                p.stepSimulation(physicsClientId=client)
                current_time = (step * time_step
                                + (sub_step + 1) * bullet_tick)
                passivate_emitted_bodies(current_time, step + 1)
                update_observers(step + 1, current_time)
                if stop_contact_started_at is None:
                    contacted_body = conditional_stop_contact()
                    if contacted_body:
                        stop_contact_started_at = current_time
                        stop_contact_body = contacted_body
                        FreeCAD.Console.PrintMessage(
                            f"BulletPhysics: conditional stop triggered at "
                            f"frame {step + 1} (t={current_time:.6f} s): "
                            f"'{contacted_body}' touched target "
                            f"'{stop_on_contact.Label}'; delay={stop_delay:.3f} s.\n")
                if (stop_contact_started_at is not None
                        and current_time - stop_contact_started_at >= stop_delay):
                    conditional_stop_reason = stop_contact_body
                    break
                # Evaluate emission triggers before destruction removes the
                # contacting Bullet body. This lets a shared target both stop
                # an emitter and destroy the incoming active body.
                update_emitter_conditions(step + 1, current_time)
                destroy_contacted_bodies()

            frame = SimulationFrame()
            speed_frame = {}
            for body_id, (rb, link, local_offset, is_emitted) in body_map.items():
                if rb.BodyType == "Passive":
                    frame[link.Name] = link.Placement.copy()
                    speed_frame[link.Name] = 0.0
                    continue
                pos, orn = p.getBasePositionAndOrientation(
                    body_id, physicsClientId=client)
                linear, _angular = p.getBaseVelocity(
                    body_id, physicsClientId=client)

                new_rot = FreeCAD.Rotation(orn[0], orn[1], orn[2], orn[3])
                new_world_center = FreeCAD.Vector(
                    pos[0] * M_TO_MM,
                    pos[1] * M_TO_MM,
                    pos[2] * M_TO_MM,
                )
                new_base = new_world_center - new_rot.multVec(local_offset)
                frame[link.Name] = FreeCAD.Placement(new_base, new_rot)
                speed_frame[link.Name] = sum(value * value for value in linear) ** 0.5
            frame.passive_link_names = tuple(
                link.Name for body_id, (_rb, link, _offset, _emitted) in body_map.items()
                if not body_is_active(body_id, body_map.get(body_id)))

            frames.append(frame)
            speed_frames.append(speed_frame)

            if conditional_stop_reason:
                if stop_delay > 0.0:
                    _last_stop_reason = (
                        f"'{conditional_stop_reason}' touched "
                        f"'{stop_on_contact.Label}', then waited "
                        f"{stop_delay:.3f} s")
                else:
                    _last_stop_reason = (
                        f"'{conditional_stop_reason}' touched "
                        f"'{stop_on_contact.Label}'")
                FreeCAD.Console.PrintMessage(
                    f"BulletPhysics: simulation stopped at frame {step + 1} "
                    f"(t={current_time:.6f} s) because {_last_stop_reason}.\n")
                break

            if stop_when_settled:
                if active_bodies_settled(step):
                    settled_elapsed += time_step
                else:
                    settled_elapsed = 0.0
                if settled_elapsed >= settle_duration:
                    _last_stop_reason = (
                        "all active bodies settled below "
                        f"{settle_linear:g} m/s and {settle_angular:g} rad/s "
                        f"for {settled_elapsed:.3f} s")
                    FreeCAD.Console.PrintMessage(
                        f"BulletPhysics: simulation stopped because {_last_stop_reason}.\n")
                    break

            if callback:
                if callback(step + 1, steps, frames, speed_frames, time_step) is False:
                    FreeCAD.Console.PrintMessage(
                        f"BulletPhysics: simulation stopped after {step + 1} frames.\n")
                    break

        return frames, time_step, speed_frames

    except KeyboardInterrupt:
        FreeCAD.Console.PrintMessage(
            "BulletPhysics: simulation interrupted; disconnecting Bullet.\n")
        raise

    finally:
        p.disconnect(client)
        _last_compute_time_seconds = time.perf_counter() - compute_started_at
        FreeCAD.Console.PrintMessage(
            "BulletPhysics: simulation computation time: {:.3f} s\n"
            .format(_last_compute_time_seconds))


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


def save_simulation_cache(frames, time_per_frame, speed_frames=None, doc=None):
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
        "passive_links": [
            list(getattr(frame, "passive_link_names", ())) for frame in frames
        ],
        "speeds": speed_frames or [],
    }
    with open(path, "w") as f:
        json.dump(data, f)
    FreeCAD.Console.PrintMessage(
        f"BulletPhysics: simulation cache saved → {path}\n")


def load_simulation_cache(doc=None):
    """Return (frames, time_per_frame, speed_frames) from the cache file."""
    import json, os
    path = _cache_path(doc)
    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        time_per_frame = float(data["time_per_frame"])
        frames = []
        passive_link_frames = data.get("passive_links", [])
        for index, fd in enumerate(data["frames"]):
            frame = SimulationFrame(
                passive_link_names=(passive_link_frames[index]
                                    if index < len(passive_link_frames) else ()))
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
        speed_frames = data.get("speeds", [])
        return frames, time_per_frame, speed_frames
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

def _build_collision_wireframe_shape(fc_shape, orig_pl, forced_type=None):
    """
    Return (part_shape, local_offset_mm) where part_shape is a Part solid
    representing the collision envelope, centered at its local origin (so that
    setting Part::Feature.Placement = Placement(collision_center, rot) places
    it correctly in the 3D view).

    local_offset_mm is the FreeCAD-unit (mm) vector from orig_pl.Base to the
    collision centre, expressed in the body's local frame.

    *forced_type* overrides auto-detection ('box', 'sphere', 'cylinder', 'mesh', 'convex_hull').
    """
    import Part

    bb = fc_shape.BoundBox
    world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
    inv_rot = orig_pl.Rotation.inverted()
    local_offset = inv_rot.multVec(world_center - orig_pl.Base)

    half = _local_half_extents(fc_shape, orig_pl)   # [hx, hy, hz] in mm
    shape_type = forced_type or _detect_freecad_shape_type(fc_shape)

    if shape_type == "sphere":
        try:
            radius = fc_shape.Faces[0].Surface.Radius
        except Exception:
            radius = (half[0] + half[1] + half[2]) / 3.0
        wf = Part.makeSphere(radius)
        # Part.makeSphere is already centred at origin — no transform needed

    elif shape_type == "cylinder":
        try:
            cyl_face  = next((f for f in fc_shape.Faces
                              if "Cylinder" in type(f.Surface).__name__), None)
            seam_edge = next((e for e in fc_shape.Edges
                              if "Line" in type(e.Curve).__name__), None)
            if cyl_face is None or seam_edge is None:
                raise ValueError("cylinder geometry not found")
            radius = cyl_face.Surface.Radius
            height = seam_edge.Length
        except Exception:
            half_sorted = sorted(half)
            radius = (half_sorted[0] + half_sorted[1]) / 2.0
            height = half_sorted[2] * 2.0
        wf = Part.makeCylinder(radius, height)
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(0.0, 0.0, -height / 2.0))
        wf = wf.transformGeometry(mat)

    elif shape_type == "box":
        hx, hy, hz = half
        wf = Part.makeBox(hx * 2.0, hy * 2.0, hz * 2.0)
        mat = FreeCAD.Matrix()
        mat.move(FreeCAD.Vector(-hx, -hy, -hz))
        wf = wf.transformGeometry(mat)

    else:   # mesh — return world-space copy; caller uses delta placement
        # transformGeometry is unreliable for complex PartDesign BRep solids
        # (may silently mis-center or raise for non-analytic geometry).
        # Instead, keep the shape in its original world-space coordinates and
        # let create/update_collision_wireframes drive position via delta
        # placement: obj.Placement = link_pl * orig_pl^{-1}.
        return fc_shape.copy(), orig_pl   # orig_pl signals "delta placement" mode

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

        override = getattr(rb, "ShapeOverride", "Auto")
        forced_type = None if override == "Auto" else override
        wf_shape, extra = _build_collision_wireframe_shape(
            fc_shape, orig_pl, forced_type=forced_type)

        obj = doc.addObject("Part::Feature", f"_BtWF_{rb.Label}")
        obj.Label  = f"Collision: {rb.Label}"
        obj.Shape  = wf_shape

        if isinstance(extra, FreeCAD.Placement):
            # Mesh mode: fc_shape.copy() strips the OCCT TopLoc_Location, leaving
            # the geometry in object-local coordinates. Apply orig_pl so FreeCAD
            # maps the local shape to world space correctly.
            obj.Placement = extra          # extra == orig_pl
        else:
            local_offset = extra
            col_center = orig_pl.Base + orig_pl.Rotation.multVec(local_offset)
            obj.Placement = FreeCAD.Placement(col_center, orig_pl.Rotation)

        if FreeCAD.GuiUp:
            import FreeCADGui
            vobj = obj.ViewObject
            vobj.DisplayMode = "Wireframe"
            vobj.LineColor   = (0.0, 1.0, 0.0)
            vobj.LineWidth   = 2.0
            vobj.Selectable  = False

        result.append((obj, rb.BodyLink.Name, extra))

    doc.recompute()
    return result


def update_collision_wireframes(wireframe_infos, frame):
    """
    Reposition each wireframe to match the given simulation frame.
    Passive bodies are not in *frame*, so their wireframes stay in place
    (correct, since passive bodies do not move).
    """
    for (obj, link_name, extra) in wireframe_infos:
        if link_name not in frame:
            continue
        link_pl = frame[link_name]
        if isinstance(extra, FreeCAD.Placement):
            # Mesh mode: shape is in local coords; link_pl is the new world placement.
            obj.Placement = link_pl
        else:
            local_offset = extra
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


# ---------------------------------------------------------------------------
# Tessellated collision mesh visualisation
# ---------------------------------------------------------------------------

def create_collision_mesh_displays(doc=None):
    """
    Create orange wireframe Mesh::Feature objects showing the actual tessellated
    triangle mesh used for collision, for each body whose effective collision
    shape is 'mesh' or 'convex_hull'.  Primitives (box, sphere, cylinder) are
    skipped since they use analytic shapes with no tessellation.

    Returns a list of (obj, link_name, local_offset_mm) tuples for animation
    updates.  local_offset_mm is the vector (in body-local mm) from the link's
    placement origin to the bbox centre — same convention used by run_simulation.
    """
    if doc is None:
        doc = FreeCAD.ActiveDocument

    mesh_settings = _find_mesh_settings(doc)
    mesh_res = max(0.001, getattr(mesh_settings, "MeshSize", 1.0))

    result = []

    def add_display(fc_shape, orig_pl, label, link_name):
        """Create one orange display mesh in the same local frame as a Link."""
        import Mesh as _Mesh

        bb = fc_shape.BoundBox
        world_center = FreeCAD.Vector(bb.Center.x, bb.Center.y, bb.Center.z)
        inv_rot = orig_pl.Rotation.inverted()
        local_offset = inv_rot.multVec(world_center - orig_pl.Base)
        verts_world, tri_faces = fc_shape.tessellate(mesh_res)
        verts_local = [inv_rot.multVec(FreeCAD.Vector(
            vertex.x - world_center.x,
            vertex.y - world_center.y,
            vertex.z - world_center.z)) for vertex in verts_world]
        triangles = [(verts_local[i0], verts_local[i1], verts_local[i2])
                     for i0, i1, i2 in tri_faces]
        obj = doc.addObject("Mesh::Feature", f"_BtCollisionMesh_{link_name}")
        obj.Label = f"Collision Mesh: {label}"
        obj.Mesh = _Mesh.Mesh(triangles)
        obj.Placement = FreeCAD.Placement(world_center, orig_pl.Rotation)
        if FreeCAD.GuiUp:
            vobj = obj.ViewObject
            vobj.DisplayMode = "Wireframe"
            vobj.LineColor = (1.0, 0.5, 0.0)
            vobj.LineWidth = 1.0
            vobj.Selectable = False
        result.append((obj, link_name, local_offset))

    for rb in collect_rigid_bodies(doc):
        override = getattr(rb, "ShapeOverride", "Auto")
        fc_shape = rb.OriginalObject.Shape
        orig_pl  = rb.OriginalObject.Placement

        eff_type = (_detect_freecad_shape_type(fc_shape)
                    if override == "Auto" else override)

        if eff_type not in ("mesh", "convex_hull"):
            continue

        try:
            add_display(fc_shape, orig_pl, rb.Label, rb.BodyLink.Name)

        except Exception as exc:
            FreeCAD.Console.PrintWarning(
                f"BulletPhysics: mesh display failed for {rb.Label}: {exc}\n"
            )

    # Emitter links share the template's collision shape but have independent
    # placements and visibility during playback, so each link gets a display.
    for emitter in collect_emitters(doc):
        for link in getattr(emitter, "GeneratedLinks", []):
            if link is None:
                continue
            template = getattr(link, "LinkedObject", None)
            if template is None:
                template = emitter.TemplateObject
            try:
                add_display(template.Shape, template.Placement, link.Label, link.Name)
            except Exception as exc:
                FreeCAD.Console.PrintWarning(
                    f"BulletPhysics: mesh display failed for {link.Label}: {exc}\n")

    doc.recompute()
    return result


def update_collision_mesh_displays(mesh_infos, frame):
    """Reposition each mesh display to match the given simulation frame."""
    for (obj, link_name, local_offset) in mesh_infos:
        if link_name not in frame:
            if FreeCAD.GuiUp:
                obj.ViewObject.Visibility = False
            continue
        link_pl = frame[link_name]
        # Recover the bbox world centre from the link placement + stored offset.
        new_world_center = link_pl.Base + link_pl.Rotation.multVec(local_offset)
        obj.Placement = FreeCAD.Placement(new_world_center, link_pl.Rotation)
        if FreeCAD.GuiUp:
            obj.ViewObject.Visibility = True


def remove_collision_mesh_displays(mesh_infos, doc=None):
    """Delete all mesh display objects from the document."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    for (obj, _, _) in mesh_infos:
        try:
            doc.removeObject(obj.Name)
        except Exception:
            pass
    if mesh_infos:
        doc.recompute()


def cleanup_stale_mesh_displays(doc=None):
    """Remove leftover collision-mesh displays without deleting global meshes."""
    if doc is None:
        doc = FreeCAD.ActiveDocument
    if doc is None:
        return
    stale = [o for o in doc.Objects
             if (o.Name.startswith("_BtCollisionMesh_")
                 or (o.Name.startswith("_BtMesh_")
                     and not hasattr(o, "SourceObject")))]
    for o in stale:
        doc.removeObject(o.Name)
    if stale:
        doc.recompute()


def _show_install_error():
    from PySide.QtWidgets import QMessageBox

    QMessageBox.critical(
        None,
        "pybullet not installed, pybullet is required.\n",
        "See instructions: github.com/kevinsmia1939/FreeCAD-BulletPhysics",
    )
