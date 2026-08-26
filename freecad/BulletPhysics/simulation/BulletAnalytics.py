import FreeCAD


def show_speed_plot(frames, time_step, x_axis="Time", speed_frames=None,
                    figure_name=None, show_legend=True):
    """Open a FreeCAD Plot speed trace for every particle in *frames*."""
    if len(frames) < 2:
        raise ValueError("Run the simulation for at least one frame before plotting speed.")

    try:
        from FreeCAD.Plot import Plot
    except ImportError as exc:
        raise RuntimeError(
            "FreeCAD's Plot module is unavailable. Install or enable the Plot workbench.") from exc

    series = {}
    has_recorded_speeds = speed_frames is not None and len(speed_frames) == len(frames)
    for frame_index in range(1, len(frames)):
        previous = frames[frame_index - 1]
        current = frames[frame_index]
        x_value = frame_index if x_axis == "Frame" else frame_index * time_step
        for link_name, placement in current.items():
            if has_recorded_speeds and link_name in speed_frames[frame_index]:
                speed = speed_frames[frame_index][link_name]
            else:
                old_placement = previous.get(link_name)
                if old_placement is None:
                    continue
                displacement_mm = (placement.Base - old_placement.Base).Length
                speed = displacement_mm * 0.001 / time_step
            series.setdefault(link_name, ([], []))
            series[link_name][0].append(x_value)
            series[link_name][1].append(speed)

    if not series:
        raise ValueError("No particle velocity data is available in the simulation frames.")

    document_name = FreeCAD.ActiveDocument.Name if FreeCAD.ActiveDocument else "Bullet Physics"
    figure = Plot.figure(figure_name or f"{document_name} : Particle Speed")
    axes = figure.axes
    axes.cla()
    axes.set_title("Particle Speed")
    axes.set_xlabel("Simulation frame" if x_axis == "Frame" else "Simulation time (s)")
    axes.set_ylabel("Speed (m/s)")
    for link_name, (x_values, speeds) in series.items():
        obj = FreeCAD.ActiveDocument.getObject(link_name) if FreeCAD.ActiveDocument else None
        label = obj.Label if obj is not None else link_name
        axes.plot(x_values, speeds, label=label, linewidth=1)
    axes.grid()
    if show_legend:
        axes.legend(loc="upper right")
    figure.canvas.draw()
    return figure
