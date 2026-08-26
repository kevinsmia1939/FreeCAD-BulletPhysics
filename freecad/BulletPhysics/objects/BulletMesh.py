import math
import os
import shutil
import subprocess
import tempfile

import FreeCAD


def source_shape_signature(shape):
    """Return a stable, lightweight signature for generated-mesh validation."""
    bb = shape.BoundBox
    return "|".join("{:.9g}".format(value) for value in (
        shape.Volume, shape.Area,
        bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax,
        len(shape.Vertexes), len(shape.Edges), len(shape.Faces), len(shape.Solids),
    ))


class MeshSettingsFeature:
    """One global meshing configuration shared by every rigid body."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyEnumeration", "Mesher", "Meshing",
                        "Meshing backend")
        obj.Mesher = ["Standard", "Gmsh"]
        obj.addProperty("App::PropertyFloat", "MeshSize", "Meshing",
                        "Maximum element size in mm for all rigid bodies")
        obj.MeshSize = 1.0
        obj.addProperty("App::PropertyFloat", "AngularDeflection", "Meshing",
                        "Maximum angular deflection in degrees for all rigid bodies")
        obj.AngularDeflection = 30.0
        obj.addProperty("App::PropertyLinkList", "GeneratedMeshes", "Meshing",
                        "Meshes generated from the current global parameters")
        obj.addProperty("App::PropertyFloat", "GeneratedMeshSize", "Meshing State")
        obj.addProperty("App::PropertyFloat", "GeneratedAngularDeflection", "Meshing State")
        obj.addProperty("App::PropertyString", "GeneratedMesher", "Meshing State")
        obj.addProperty("App::PropertyBool", "ShowCollisionMesh", "Display",
                        "Show orange collision-mesh wireframes during simulation playback")
        obj.ShowCollisionMesh = False
        obj.Proxy = self

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        if not hasattr(obj, "ShowCollisionMesh"):
            obj.addProperty("App::PropertyBool", "ShowCollisionMesh", "Display",
                            "Show orange collision-mesh wireframes during simulation playback")
            obj.ShowCollisionMesh = False
        if FreeCAD.GuiUp:
            obj.ViewObject.Visibility = True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def _mesh_from_gmsh(shape, mesh_size):
    gmsh = shutil.which("gmsh")
    if gmsh is None:
        raise RuntimeError("Gmsh is not available on PATH. Install Gmsh or choose Standard.")
    import Mesh
    with tempfile.TemporaryDirectory() as directory:
        brep_path = os.path.join(directory, "shape.brep")
        msh_path = os.path.join(directory, "shape.msh")
        shape.exportBrep(brep_path)
        result = subprocess.run(
            [gmsh, brep_path, "-2", "-format", "msh2",
             "-clmax", str(mesh_size), "-o", msh_path],
            capture_output=True, text=True, check=False)
        if result.returncode != 0 or not os.path.exists(msh_path):
            raise RuntimeError(result.stderr.strip() or "Gmsh failed to generate a mesh.")

        nodes, triangles = {}, []
        with open(msh_path, encoding="utf-8") as msh_file:
            lines = iter(line.strip() for line in msh_file)
            for line in lines:
                if line == "$Nodes":
                    for _ in range(int(next(lines))):
                        values = next(lines).split()
                        nodes[int(values[0])] = FreeCAD.Vector(
                            float(values[1]), float(values[2]), float(values[3]))
                elif line == "$Elements":
                    for _ in range(int(next(lines))):
                        values = next(lines).split()
                        if int(values[1]) == 2:  # Triangle element
                            tags = int(values[2])
                            triangles.append(tuple(int(node) for node in values[3 + tags:6 + tags]))

        mesh = Mesh.Mesh()
        for node_a, node_b, node_c in triangles:
            mesh.addFacet(nodes[node_a], nodes[node_b], nodes[node_c])
        if mesh.CountFacets == 0:
            raise RuntimeError("Gmsh produced no surface facets.")
        return mesh


def _generate_mesh(shape, mesher, mesh_size, angular_deflection):
    if mesher == "Gmsh":
        return _mesh_from_gmsh(shape, mesh_size)
    import MeshPart
    return MeshPart.meshFromShape(
        Shape=shape,
        LinearDeflection=mesh_size,
        AngularDeflection=math.radians(angular_deflection),
        Relative=False)


def generate_meshes(settings):
    """Generate meshes for every enabled rigid body with shared settings."""
    from ..simulation.BulletSimulation import collect_emitters, collect_rigid_bodies

    doc = settings.Document
    mesh_size = max(0.001, settings.MeshSize)
    angle = max(0.1, min(180.0, settings.AngularDeflection))
    old_meshes = list(settings.GeneratedMeshes)
    for mesh_obj in old_meshes:
        if mesh_obj is not None:
            doc.removeObject(mesh_obj.Name)
    settings.GeneratedMeshes = []
    doc.recompute()

    meshes = []
    source_objects = [rigid_body.OriginalObject
                      for rigid_body in collect_rigid_bodies(doc)]
    from ..simulation.BulletSimulation import emitter_template_entries
    source_objects.extend(template for emitter in collect_emitters(doc)
                          for template, _ratio in emitter_template_entries(emitter))
    unique_sources = {source.Name: source for source in source_objects}
    for source in unique_sources.values():
        mesh_obj = doc.addObject("Mesh::Feature", f"_BtGlobalMesh_{source.Name}")
        mesh_obj.addProperty("App::PropertyLink", "SourceObject", "Bullet Physics")
        mesh_obj.addProperty("App::PropertyString", "SourceShapeSignature",
                             "Bullet Physics",
                             "Source geometry state when this mesh was generated")
        mesh_obj.SourceObject = source
        mesh_obj.SourceShapeSignature = source_shape_signature(source.Shape)
        mesh_obj.Label = f"Mesh: {source.Label}"
        mesh_obj.Mesh = _generate_mesh(
            source.Shape, settings.Mesher, mesh_size, angle)
        if FreeCAD.GuiUp:
            mesh_obj.ViewObject.Visibility = False
        meshes.append(mesh_obj)

    settings.GeneratedMeshes = meshes
    settings.GeneratedMeshSize = mesh_size
    settings.GeneratedAngularDeflection = angle
    settings.GeneratedMesher = settings.Mesher
    doc.recompute()
    return len(meshes)


class MeshSettingsPanel:
    def __init__(self, settings):
        from PySide import QtWidgets

        self._settings = settings
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Mesh from Shape")
        layout = QtWidgets.QVBoxLayout(self.form)
        form = QtWidgets.QFormLayout()

        self.mesher = QtWidgets.QComboBox()
        self.mesher.addItems(["Standard", "Gmsh"])
        self.mesher.setCurrentText(settings.Mesher)
        self.mesh_size = QtWidgets.QDoubleSpinBox()
        self.mesh_size.setRange(0.001, 100000.0)
        self.mesh_size.setDecimals(4)
        self.mesh_size.setSuffix(" mm")
        self.mesh_size.setValue(max(0.001, settings.MeshSize))
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0.1, 180.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" deg")
        self.angle.setValue(max(0.1, settings.AngularDeflection))
        form.addRow("Mesher:", self.mesher)
        form.addRow("Mesh size:", self.mesh_size)
        form.addRow("Angular deflection:", self.angle)
        layout.addLayout(form)

        self.status = QtWidgets.QLabel(
            "Generate meshes for every enabled active and passive rigid body.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.show_collision_mesh = QtWidgets.QCheckBox("Show collision mesh")
        self.show_collision_mesh.setToolTip(
            "Display orange wireframes for the tessellated collision meshes. "
            "They update during simulation playback.")
        self.show_collision_mesh.setChecked(getattr(settings, "ShowCollisionMesh", False))
        layout.addWidget(self.show_collision_mesh)
        self.generate_button = QtWidgets.QPushButton("Generate Meshes")
        self.generate_button.clicked.connect(self._generate)
        layout.addWidget(self.generate_button)
        layout.addStretch()
        self.show_collision_mesh.toggled.connect(self._on_show_collision_mesh)

    def _save(self):
        self._settings.Mesher = self.mesher.currentText()
        self._settings.MeshSize = self.mesh_size.value()
        self._settings.AngularDeflection = self.angle.value()
        self._settings.ShowCollisionMesh = self.show_collision_mesh.isChecked()

    def _on_show_collision_mesh(self, visible):
        """Show or remove the static collision-mesh preview immediately."""
        self._save()
        from ..simulation.BulletSimulation import (
            cleanup_stale_mesh_displays, create_collision_mesh_displays)
        cleanup_stale_mesh_displays(self._settings.Document)
        if visible:
            create_collision_mesh_displays(self._settings.Document)

    def _generate(self):
        from PySide import QtWidgets
        self._save()
        try:
            count = generate_meshes(self._settings)
            self.status.setText(f"Generated {count} rigid-body mesh(es).")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(None, "Mesh Generation Failed", str(exc))
            self.status.setText(f"Mesh generation failed: {exc}")

    def accept(self):
        self._save()
        return True

    def reject(self):
        return True


class MeshSettingsViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .. import BulletUtils
        return os.path.join(BulletUtils.ICONS_PATH, "BulletMesh.svg")

    def claimChildren(self):
        return [mesh for mesh in self.Object.GeneratedMeshes if mesh is not None]

    def setEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.showDialog(MeshSettingsPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        return self.setEdit(vobj, 0)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


def make_mesh_settings(container):
    doc = container.Document
    # Match FreeCAD's solver-task objects: a Part::FeaturePython has an empty
    # Shape but remains an active, non-greyed tree item.
    settings = doc.addObject("Part::FeaturePython", "BulletMesh")
    MeshSettingsFeature(settings)
    settings.Label = "Mesh"
    if FreeCAD.GuiUp:
        MeshSettingsViewProvider(settings.ViewObject)
        # This is a settings object, not geometry. Keep its tree icon active.
        settings.ViewObject.Visibility = True
    container.MeshSettings = settings
    doc.recompute()
    return settings
