"""Sweep packed-bed diameter and calculate ROI packing density.

Run from FreeCAD's Python console or with FreeCADCmd after the Bullet Physics
addon and pybullet are available::

    exec(open("/path/to/sweep_packing_density.py").read())

Each sweep starts from a fresh copy of the source document.  The script keeps
all existing simulation settings unchanged, sets ``VarSet.bed_diameter`` for
the requested bed diameter, runs the simulation, then fuses surviving emitted
particles and intersects them with the ROI solid. Results are written to CSV.
"""

from __future__ import print_function

import csv
from pathlib import Path
import secrets

import FreeCAD as App


SOURCE_DOCUMENT = Path(
    "/home/kevin/Dropbox/UAntwerp/PhD_thesis/FreeCAD_files/"
    "packed_bed_void.FCStd")
OUTPUT_DIRECTORY = SOURCE_DOCUMENT.parent / "packing_density_sweep"
BED_DIAMETERS_MM = (10.0, 15.0, 20.0, 25.0, 30.0, 35.0)

VARIABLE_SET_NAME = "VarSet"
BED_DIAMETER_PROPERTY = "bed_diameter"
ROI_LABEL = "ROI"


def _set_length(obj, property_name, value_mm):
    """Set a FreeCAD length property while supporting old document objects."""
    try:
        setattr(obj, property_name, "{} mm".format(value_mm))
    except (TypeError, ValueError):
        setattr(obj, property_name, value_mm)


def set_bed_diameter(document, diameter_mm):
    """Set the model's VarSet.bed_diameter parameter in millimetres."""
    var_set = document.getObject(VARIABLE_SET_NAME)
    if var_set is None:
        raise RuntimeError("Variable set {!r} was not found.".format(VARIABLE_SET_NAME))
    if not hasattr(var_set, BED_DIAMETER_PROPERTY):
        raise RuntimeError(
            "Variable {!r} was not found on {}."
            .format(BED_DIAMETER_PROPERTY, VARIABLE_SET_NAME))
    _set_length(var_set, BED_DIAMETER_PROPERTY, diameter_mm)
    return "{}.{}".format(VARIABLE_SET_NAME, BED_DIAMETER_PROPERTY)


def randomize_emitter_seeds(document):
    """Assign independent nonzero orientation and direction seeds to emitters."""
    from freecad.BulletPhysics.simulation.BulletSimulation import collect_emitters

    emitters = collect_emitters(document, enabled_only=False)
    for emitter in emitters:
        emitter.RandomSeed = secrets.randbelow(2147483647) + 1
        emitter.DirectionRandomSeed = secrets.randbelow(2147483647) + 1
    return len(emitters)


def simulation_progress(diameter_mm):
    """Create a callback that prints simulation progress in five-percent steps."""
    last_percent = [-1]

    def report(step, total_steps, _frames, _speed_frames, time_step):
        percent = int(step * 100 / total_steps) if total_steps else 100
        if percent // 5 > last_percent[0] // 5 or step == total_steps:
            print("{:.6g} mm: simulation {:d}/{:d} ({:d}%), t={:.3f} s"
                  .format(diameter_mm, step, total_steps, percent, step * time_step))
            last_percent[0] = percent
        return True

    return report


def refresh_collision_meshes(document):
    """Regenerate all collision meshes from the current recomputed geometry."""
    from freecad.BulletPhysics.objects.BulletMesh import generate_meshes
    from freecad.BulletPhysics.simulation.BulletSimulation import _find_mesh_settings

    settings = _find_mesh_settings(document)
    if settings is None:
        raise RuntimeError("Global Bullet Physics Mesh object was not found.")
    return generate_meshes(settings)


def generate_velocity_plot(diameter_mm, frames, time_step, speed_frames):
    """Open a distinct particle-speed plot for the completed sweep case."""
    if not App.GuiUp:
        print("  Velocity plot skipped because the FreeCAD GUI is unavailable.")
        return False

    from freecad.BulletPhysics.simulation.BulletAnalytics import show_speed_plot

    figure_name = "Packing density {:.6g} mm : Particle Speed".format(diameter_mm)
    show_speed_plot(frames, time_step, speed_frames=speed_frames,
                    figure_name=figure_name, show_legend=False)
    print("  Velocity plot generated: {}".format(figure_name))
    return True


def find_roi(document):
    for obj in document.Objects:
        if obj.Label == ROI_LABEL and hasattr(obj, "Shape") and not obj.Shape.isNull():
            return obj
    raise RuntimeError("ROI object with label {!r} was not found.".format(ROI_LABEL))


def surviving_particle_links(document, final_frame):
    """Return emitted-particle links that are still simulated in the last frame."""
    from freecad.BulletPhysics.simulation.BulletSimulation import collect_emitters

    final_names = set(final_frame)
    links = []
    for emitter in collect_emitters(document, enabled_only=False):
        for link in getattr(emitter, "GeneratedLinks", []):
            if link is not None and link.Name in final_names:
                links.append(link)
    return links


def packing_density(document, final_frame):
    """Fuse surviving particles, intersect with ROI, and return density data."""
    roi = find_roi(document)
    particles = surviving_particle_links(document, final_frame)
    if not particles:
        return 0, 0.0, roi.Shape.Volume, 0.0

    shapes = [link.Shape.copy() for link in particles if not link.Shape.isNull()]
    if not shapes:
        return 0, 0.0, roi.Shape.Volume, 0.0

    fused_particles = shapes[0].multiFuse(shapes[1:]) if len(shapes) > 1 else shapes[0]
    packed_in_roi = fused_particles.common(roi.Shape)
    roi_volume = roi.Shape.Volume
    packed_volume = packed_in_roi.Volume
    density = packed_volume / roi_volume if roi_volume > 0.0 else 0.0
    return len(shapes), packed_volume, roi_volume, density


def run_sweep():
    from freecad.BulletPhysics.simulation.BulletSimulation import apply_frame, run_simulation

    if not SOURCE_DOCUMENT.is_file():
        raise RuntimeError("Source document does not exist: {}".format(SOURCE_DOCUMENT))
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIRECTORY / "packing_density.csv"
    rows = []

    for diameter_mm in BED_DIAMETERS_MM:
        document = App.openDocument(str(SOURCE_DOCUMENT))
        try:
            changed_property = set_bed_diameter(document, diameter_mm)
            emitter_count = randomize_emitter_seeds(document)
            document.recompute()
            mesh_count = refresh_collision_meshes(document)
            print("\nStarting {:.6g} mm sweep".format(diameter_mm))
            print("  {} = {}".format(
                changed_property, getattr(document.getObject(VARIABLE_SET_NAME),
                                           BED_DIAMETER_PROPERTY)))
            print("  Randomized seeds for {:d} emitter(s)".format(emitter_count))
            print("  Regenerated {:d} collision mesh(es) from current geometry"
                  .format(mesh_count))

            result = run_simulation(callback=simulation_progress(diameter_mm))
            if not result:
                raise RuntimeError("Bullet simulation failed for {} mm.".format(diameter_mm))
            frames = result[0]
            time_step = result[1]
            speed_frames = result[2] if len(result) > 2 else None
            if not frames:
                raise RuntimeError("Bullet simulation returned no frames for {} mm.".format(diameter_mm))
            apply_frame(frames[-1])
            document.recompute()
            generate_velocity_plot(diameter_mm, frames, time_step, speed_frames)

            particle_count, packed_volume, roi_volume, density = packing_density(
                document, frames[-1])
            row = {
                "bed_diameter_mm": diameter_mm,
                "changed_property": changed_property,
                "randomized_emitters": emitter_count,
                "surviving_particles": particle_count,
                "particle_volume_in_roi_mm3": packed_volume,
                "roi_volume_mm3": roi_volume,
                "packing_density": density,
            }
            rows.append(row)
            print("{bed_diameter_mm:g} mm complete: packing volume="
                  "{particle_volume_in_roi_mm3:.8f} mm^3, ROI volume="
                  "{roi_volume_mm3:.8f} mm^3, density={packing_density:.8f} "
                  "({surviving_particles} surviving particles)".format(**row))
        finally:
            App.closeDocument(document.Name)

    with csv_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=(
            "bed_diameter_mm", "changed_property", "surviving_particles",
            "randomized_emitters", "particle_volume_in_roi_mm3", "roi_volume_mm3",
            "packing_density"))
        writer.writeheader()
        writer.writerows(rows)
    print("Packing-density sweep written to {}".format(csv_path))
    return rows


if __name__ == "__main__":
    run_sweep()
