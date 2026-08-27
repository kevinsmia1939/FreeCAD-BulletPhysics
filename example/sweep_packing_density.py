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
import math
import os
from pathlib import Path
import secrets
import time

import FreeCAD as App


SOURCE_DOCUMENT = Path(
    "/home/kevin/Dropbox/UAntwerp/PhD_thesis/FreeCAD_files/"
    "packed_bed_void.FCStd")
OUTPUT_DIRECTORY = SOURCE_DOCUMENT.parent / "packing_density_sweep"
BED_DIAMETERS_MM = (6,8,10,11,12,13,14,15,16,18,20,22.5,25,30,35,40,45,50,55,60)

VARIABLE_SET_NAME = "VarSet"
BED_DIAMETER_PROPERTY = "bed_diameter"
PARTICLE_LENGTH_PROPERTY = "particle_length"
ROI_LABEL = "ROI"
CSV_FIELDS = (
    "bed_diameter_mm", "particle_length_mm", "changed_property",
    "surviving_particles", "randomized_emitters",
    "calculated_packing_volume_mm3", "normalization_volume_mm3",
    "packing_density_percent", "simulation_compute_time_seconds")


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


def varset_length_mm(document, property_name):
    """Return a length parameter from VarSet in millimetres."""
    var_set = document.getObject(VARIABLE_SET_NAME)
    if var_set is None or not hasattr(var_set, property_name):
        raise RuntimeError(
            "Variable {!r} was not found on {}."
            .format(property_name, VARIABLE_SET_NAME))
    value = getattr(var_set, property_name)
    return value.Value if hasattr(value, "Value") else float(value)


def randomize_emitter_seeds(document):
    """Assign independent nonzero orientation and direction seeds to emitters."""
    from freecad.BulletPhysics.simulation.BulletSimulation import collect_emitters

    emitters = collect_emitters(document, enabled_only=False)
    for emitter in emitters:
        emitter.RandomSeed = secrets.randbelow(2147483647) + 1
        emitter.DirectionRandomSeed = secrets.randbelow(2147483647) + 1
    return len(emitters)


def simulation_progress(diameter_mm):
    """Create a callback with percentage and five-minute wall-time reports."""
    last_percent = [-1]
    started_at = time.monotonic()
    last_wall_report_at = [started_at]

    def report(step, total_steps, _frames, _speed_frames, time_step):
        percent = int(step * 100 / total_steps) if total_steps else 100
        if percent // 5 > last_percent[0] // 5 or step == total_steps:
            print("{:.6g} mm: simulation {:d}/{:d} ({:d}%), t={:.3f} s"
                  .format(diameter_mm, step, total_steps, percent, step * time_step))
            last_percent[0] = percent
        now = time.monotonic()
        if now - last_wall_report_at[0] >= 300.0:
            print("{:.6g} mm: wall-time checkpoint at {:.1f} min: frame "
                  "{:d}/{:d}, simulation t={:.3f} s"
                  .format(diameter_mm, (now - started_at) / 60.0,
                          step, total_steps, step * time_step))
            last_wall_report_at[0] = now
        if App.GuiUp and step % 20 == 0 and _frames:
            # Show a periodic still frame without starting playback.
            from freecad.BulletPhysics.simulation.BulletSimulation import apply_frame
            apply_frame(_frames[-1])
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


def conditional_stop_settings(document):
    """Return the enabled conditional-stop target and contact delay."""
    from freecad.BulletPhysics.objects.BulletWorld import find_world

    world = find_world(document)
    if world is None:
        return None, 0.0
    if hasattr(world.Proxy, "_ensure_properties"):
        world.Proxy._ensure_properties(world)
    target = getattr(world, "ConditionalStopTarget", None)
    if (not getattr(world, "ConditionalStopEnabled", False)
            or target is None
            or not hasattr(target, "Shape")
            or target.Shape is None):
        return None, 0.0
    return target, max(0.0, getattr(world, "ConditionalStopDelay", 0.0))


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
    """Return the ROI packing volume and requested bed-normalized density."""
    roi = find_roi(document)
    bed_diameter_mm = varset_length_mm(document, BED_DIAMETER_PROPERTY)
    particle_length_mm = varset_length_mm(document, PARTICLE_LENGTH_PROPERTY)
    normalization_volume = (
        (bed_diameter_mm / 2.0) ** 2 * math.pi * particle_length_mm * 5.0)
    particles = surviving_particle_links(document, final_frame)
    if not particles:
        return 0, 0.0, normalization_volume, 0.0

    shapes = [link.Shape.copy() for link in particles if not link.Shape.isNull()]
    if not shapes:
        return 0, 0.0, normalization_volume, 0.0

    fused_particles = shapes[0].multiFuse(shapes[1:]) if len(shapes) > 1 else shapes[0]
    packed_in_roi = fused_particles.common(roi.Shape)
    packed_volume = packed_in_roi.Volume
    density_percent = (packed_volume / normalization_volume * 100.0
                       if normalization_volume > 0.0 else 0.0)
    return len(shapes), packed_volume, normalization_volume, density_percent


def initialize_report(csv_path):
    """Start a fresh report and ensure its header reaches disk immediately."""
    with csv_path.open("w", newline="") as csv_file:
        csv.DictWriter(csv_file, fieldnames=CSV_FIELDS).writeheader()
        csv_file.flush()
        os.fsync(csv_file.fileno())


def append_report_row(csv_path, row):
    """Durably append one completed simulation result to the report."""
    with csv_path.open("a", newline="") as csv_file:
        csv.DictWriter(csv_file, fieldnames=CSV_FIELDS).writerow(row)
        csv_file.flush()
        os.fsync(csv_file.fileno())


def run_sweep():
    from freecad.BulletPhysics.simulation.BulletSimulation import (
        apply_frame, get_last_compute_time_seconds, run_simulation)

    if not SOURCE_DOCUMENT.is_file():
        raise RuntimeError("Source document does not exist: {}".format(SOURCE_DOCUMENT))
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIRECTORY / "packing_density.csv"
    initialize_report(csv_path)
    rows = []

    for diameter_mm in BED_DIAMETERS_MM:
        document = App.openDocument(str(SOURCE_DOCUMENT))
        try:
            changed_property = set_bed_diameter(document, diameter_mm)
            emitter_count = randomize_emitter_seeds(document)
            document.recompute()
            mesh_count = refresh_collision_meshes(document)
            stop_target, stop_delay = conditional_stop_settings(document)
            print("\nStarting {:.6g} mm sweep".format(diameter_mm))
            print("  {} = {}".format(
                changed_property, getattr(document.getObject(VARIABLE_SET_NAME),
                                           BED_DIAMETER_PROPERTY)))
            print("  Randomized seeds for {:d} emitter(s)".format(emitter_count))
            print("  Regenerated {:d} collision mesh(es) from current geometry"
                  .format(mesh_count))
            if stop_target is not None:
                print("  Conditional stop: '{}' after {:.3f} s"
                      .format(stop_target.Label, stop_delay))

            result = run_simulation(
                callback=simulation_progress(diameter_mm),
                stop_on_contact=stop_target,
                stop_delay=stop_delay)
            if not result:
                raise RuntimeError("Bullet simulation failed for {} mm.".format(diameter_mm))
            frames = result[0]
            compute_time_seconds = get_last_compute_time_seconds()
            if not frames:
                raise RuntimeError("Bullet simulation returned no frames for {} mm.".format(diameter_mm))
            apply_frame(frames[-1])
            document.recompute()

            particle_count, packed_volume, normalization_volume, density_percent = packing_density(
                document, frames[-1])
            row = {
                "bed_diameter_mm": diameter_mm,
                "particle_length_mm": varset_length_mm(
                    document, PARTICLE_LENGTH_PROPERTY),
                "changed_property": changed_property,
                "randomized_emitters": emitter_count,
                "surviving_particles": particle_count,
                "calculated_packing_volume_mm3": packed_volume,
                "normalization_volume_mm3": normalization_volume,
                "packing_density_percent": density_percent,
                "simulation_compute_time_seconds": compute_time_seconds,
            }
            rows.append(row)
            append_report_row(csv_path, row)
            print("{bed_diameter_mm:g} mm complete: packing volume="
                  "{calculated_packing_volume_mm3:.8f} mm^3, normalization volume="
                  "{normalization_volume_mm3:.8f} mm^3, density="
                  "{packing_density_percent:.8f}% "
                  "(computed in {simulation_compute_time_seconds:.3f} s; "
                  "{surviving_particles} surviving particles)".format(**row))
            print("  Result saved to {}".format(csv_path))
        except KeyboardInterrupt:
            print("\nSweep interrupted. Bullet simulation stopped; "
                  "{:d} completed result(s) remain in {}."
                  .format(len(rows), csv_path))
            return rows
        finally:
            App.closeDocument(document.Name)

    print("Packing-density sweep written to {}".format(csv_path))
    return rows


if __name__ == "__main__":
    run_sweep()
