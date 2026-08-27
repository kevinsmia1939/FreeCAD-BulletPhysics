import FreeCAD


class BulletObserverFeature:
    """Non-physical volume that reports rigid bodies within its shape."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "SourceObject", "Observer",
                        "Volume or surface used to observe rigid bodies")
        obj.addProperty("App::PropertyBool", "Enabled", "Observer",
                        "Include this observer in Bullet Physics simulations")
        obj.Enabled = True
        self._ensure_properties(obj)
        obj.addProperty("App::PropertyStringList", "CurrentBodies", "Observation",
                        "Bodies currently inside or touching the observer")
        obj.addProperty("App::PropertyString", "LastEvent", "Observation",
                        "Most recent observer event")
        obj.Proxy = self

    @staticmethod
    def _ensure_properties(obj):
        definitions = (
            ("App::PropertyEnumeration", "BodyTypeCondition", "Trigger Condition",
             "Rigid-body type required by this observer", ["Any", "Active", "Passive"]),
            ("App::PropertyEnumeration", "SpeedCondition", "Trigger Condition",
             "Optional speed comparison in m/s", ["Any", "At least", "At most"]),
            ("App::PropertyFloat", "Speed", "Trigger Condition",
             "Speed threshold in m/s", 0.0),
            ("App::PropertyEnumeration", "ConditionLogic", "Trigger Condition",
             "How enabled body-type and speed conditions are combined", ["AND", "OR"]),
            ("App::PropertyFloat", "TriggerDelay", "Trigger Condition",
             "Seconds a matching body must remain observed before triggering", 0.0),
            ("App::PropertyBool", "Triggered", "Trigger State",
             "True after this observer has emitted its signal during the simulation", False),
            ("App::PropertyString", "TriggerBody", "Trigger State",
             "Body that caused the observer signal", ""),
            ("App::PropertyFloat", "TriggerTime", "Trigger State",
             "Simulation time when the observer signal was emitted", 0.0),
        )
        for property_type, name, group, description, value in definitions:
            if hasattr(obj, name):
                continue
            obj.addProperty(property_type, name, group, description)
            setattr(obj, name, value)

    def execute(self, obj):
        pass

    def onDocumentRestored(self, obj):
        if not hasattr(obj, "Enabled"):
            obj.addProperty("App::PropertyBool", "Enabled", "Observer",
                            "Include this observer in Bullet Physics simulations")
            obj.Enabled = True
        if not hasattr(obj, "CurrentBodies"):
            obj.addProperty("App::PropertyStringList", "CurrentBodies", "Observation",
                            "Bodies currently inside or touching the observer")
        if not hasattr(obj, "LastEvent"):
            obj.addProperty("App::PropertyString", "LastEvent", "Observation",
                            "Most recent observer event")
        self._ensure_properties(obj)
        if FreeCAD.GuiUp:
            obj.ViewObject.Visibility = True

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class BulletObserverViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def setEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.showDialog(ObserverPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode):
        import FreeCADGui
        FreeCADGui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        return self.setEdit(vobj, 0)

    def getIcon(self):
        import os
        from .. import BulletUtils
        return os.path.join(BulletUtils.ICONS_PATH, "AddObserver.svg")

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class ObserverPanel:
    """Small editor for the non-physical observer configuration."""

    def __init__(self, observer):
        from PySide import QtWidgets

        self.Object = observer
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Bullet Physics Observer")
        layout = QtWidgets.QVBoxLayout(self.form)
        layout.addWidget(QtWidgets.QLabel(
            "The observer does not collide with rigid bodies. It reports bodies "
            "inside or touching the selected shape."))
        self.enabled = QtWidgets.QCheckBox("Enable observer")
        self.enabled.setChecked(observer.Enabled)
        layout.addWidget(self.enabled)
        condition_group = QtWidgets.QGroupBox("Trigger Condition")
        condition_form = QtWidgets.QFormLayout(condition_group)
        self.body_type = QtWidgets.QComboBox()
        self.body_type.addItems(["Any", "Active", "Passive"])
        self.body_type.setCurrentText(observer.BodyTypeCondition)
        self.speed_condition = QtWidgets.QComboBox()
        self.speed_condition.addItems(["Any", "At least", "At most"])
        self.speed_condition.setCurrentText(observer.SpeedCondition)
        self.speed = QtWidgets.QDoubleSpinBox()
        self.speed.setRange(0.0, 100000.0)
        self.speed.setDecimals(6)
        self.speed.setSuffix(" m/s")
        self.speed.setValue(observer.Speed)
        self.logic = QtWidgets.QComboBox()
        self.logic.addItems(["AND", "OR"])
        self.logic.setCurrentText(observer.ConditionLogic)
        self.delay = QtWidgets.QDoubleSpinBox()
        self.delay.setRange(0.0, 100000.0)
        self.delay.setDecimals(4)
        self.delay.setSuffix(" s")
        self.delay.setValue(observer.TriggerDelay)
        condition_form.addRow("Body type:", self.body_type)
        condition_form.addRow("Speed:", self.speed_condition)
        condition_form.addRow("Speed threshold:", self.speed)
        condition_form.addRow("Combine rules:", self.logic)
        condition_form.addRow("Trigger delay:", self.delay)
        layout.addWidget(condition_group)
        self.signal = QtWidgets.QLabel()
        layout.addWidget(self.signal)
        self.current = QtWidgets.QPlainTextEdit()
        self.current.setReadOnly(True)
        self.current.setPlaceholderText("No observed bodies yet.")
        layout.addWidget(self.current)
        self.speed_condition.currentIndexChanged.connect(self._update_condition_controls)
        self._update_condition_controls()
        self._refresh()

    def _update_condition_controls(self):
        self.speed.setEnabled(self.speed_condition.currentText() != "Any")

    def _refresh(self):
        self.current.setPlainText("\n".join(self.Object.CurrentBodies))
        if self.Object.Triggered:
            self.signal.setText("Triggered by {} at {:.6f} s".format(
                self.Object.TriggerBody, self.Object.TriggerTime))
        else:
            self.signal.setText("Not triggered in the current simulation.")

    def accept(self):
        self.Object.Enabled = self.enabled.isChecked()
        self.Object.BodyTypeCondition = self.body_type.currentText()
        self.Object.SpeedCondition = self.speed_condition.currentText()
        self.Object.Speed = self.speed.value()
        self.Object.ConditionLogic = self.logic.currentText()
        self.Object.TriggerDelay = self.delay.value()
        self.Object.Document.recompute()
        return True

    def reject(self):
        return True


def make_observer(source_obj, container=None):
    """Create a non-physical observer for *source_obj*."""
    doc = FreeCAD.ActiveDocument
    # Part::FeaturePython keeps this no-shape task object active in the tree.
    obj = doc.addObject("Part::FeaturePython", f"Observer_{source_obj.Name}")
    BulletObserverFeature(obj)
    obj.SourceObject = source_obj
    obj.Label = f"Observer: {source_obj.Label}"

    if FreeCAD.GuiUp:
        BulletObserverViewProvider(obj.ViewObject)
        obj.ViewObject.Visibility = True

    if container is not None:
        if not hasattr(container, "Observers"):
            container.addProperty("App::PropertyLinkList", "Observers", "Container",
                                  "Non-physical rigid-body observer objects")
        container.Observers = list(getattr(container, "Observers", [])) + [obj]

    doc.recompute()
    return obj
