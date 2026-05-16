import FreeCAD
import FreeCADGui

try:
    from PySide2.QtWidgets import QMessageBox
except ImportError:
    from PySide.QtWidgets import QMessageBox


def _button_down_icon():
    import os
    import BulletUtils

    return os.path.join(BulletUtils.MOD_PATH, "icons", "button_down.svg")


def _has_shape(obj):
    return hasattr(obj, "Shape") and obj.Shape is not None


def _selected_shape_objects():
    return [obj for obj in FreeCADGui.Selection.getSelection() if _has_shape(obj)]


def _iter_leaf_solids(shape):
    """
    Yield all leaf solids from a shape.

    FreeCAD arrays and compounds often nest compounds inside compounds, so we
    recurse through child shapes until we reach individual solids.
    """
    if shape is None or shape.isNull():
        return

    try:
        solids = list(shape.Solids)
    except Exception:
        solids = []

    if solids:
        for solid in solids:
            yield solid
        return

    try:
        children = list(shape.childShapes())
    except Exception:
        children = []

    for child in children:
        yield from _iter_leaf_solids(child)


def _global_placement(obj):
    try:
        return obj.getGlobalPlacement().copy()
    except Exception:
        return obj.Placement.copy()


def _is_identity_placement(pl):
    try:
        return pl.isIdentity()
    except Exception:
        zero_base = getattr(pl, "Base", FreeCAD.Vector())
        rot = getattr(pl, "Rotation", None)
        return (
            zero_base == FreeCAD.Vector(0.0, 0.0, 0.0)
            and rot is not None
            and getattr(rot, "isIdentity", lambda: False)()
        )


def _make_solid_copy(solid):
    solid_copy = solid.copy()

    return solid_copy


class DowngradeCommand:
    def GetResources(self):
        return {
            "Pixmap": _button_down_icon(),
            "MenuText": "Downgrade Compound",
            "ToolTip": (
                "Break selected compound or array objects into individual solid "
                "components.\n"
                "Nested compounds are flattened recursively until each output "
                "object is a single solid."
            ),
        }

    def IsActive(self):
        if FreeCAD.ActiveDocument is None:
            return False
        for obj in _selected_shape_objects():
            try:
                if len(list(_iter_leaf_solids(obj.Shape))) > 1:
                    return True
            except Exception:
                continue
        return False

    def Activated(self):
        sel = _selected_shape_objects()
        if not sel:
            QMessageBox.information(
                None,
                "Nothing Selected",
                "Select a compound or array object first.",
            )
            return

        doc = FreeCAD.ActiveDocument
        created = []

        doc.openTransaction("Downgrade Compound")
        try:
            for obj in sel:
                solids = list(_iter_leaf_solids(obj.Shape))
                if len(solids) <= 1:
                    continue

                base_label = obj.Label or obj.Name
                source_pl = _global_placement(obj)

                for index, solid in enumerate(solids, start=1):
                    solid_copy = _make_solid_copy(solid)
                    new_obj = doc.addObject("Part::Feature", f"{obj.Name}_Solid_{index}")
                    new_obj.Label = f"{base_label} Solid {index}"
                    if _is_identity_placement(solid_copy.Placement):
                        new_obj.Placement = source_pl.copy()
                    new_obj.Shape = solid_copy
                    created.append(new_obj)
        except Exception:
            doc.abortTransaction()
            raise
        else:
            doc.commitTransaction()

        if not created:
            QMessageBox.information(
                None,
                "No Downgrade Needed",
                "The selected object already contains a single solid component.",
            )
            return

        doc.recompute()


FreeCADGui.addCommand("BulletPhysics_Downgrade", DowngradeCommand())
