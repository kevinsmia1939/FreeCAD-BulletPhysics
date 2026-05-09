# FreeCAD Bullet Physics Workbench

A rigid-body physics simulation workbench for FreeCAD powered by [pybullet](https://pybullet.org). Simulate objects falling, colliding, and settling, then play back the result on an interactive timeline — all without modifying your original geometry.

---

## Features

- **Active & Passive rigid bodies** — active bodies are driven by physics; passive bodies act as static colliders (floors, walls, ramps)
- **Original geometry is never modified** — the workbench drives `App::Link` clones, leaving your original solids untouched and fully editable at all times
- **Automatic collision shape detection** — spheres, cylinders, and boxes get exact analytic collision shapes; any other solid is tessellated into a convex-hull or concave mesh automatically
- **Animation timeline** — scrubber, transport controls (first / step back / play-pause / step forward / last), adjustable playback speed (0.1× – 8×), and loop toggle
- **Simulation cache** — results are saved to disk alongside your `.FCStd` file so the timeline is available immediately on reopening the panel without re-running the simulation
- **Rigid Body Summary table** — editable overview of all bodies (type, density, friction, mesh type, mesh resolution) with bulk-apply inputs for changing multiple bodies at once
- **Bake frame as new origin** — commit any timeline frame back to the original objects as the new rest position; fully undoable with Ctrl+Z
- **Physics World settings** — gravity magnitude and direction, simulation end time, frame time step, sub-steps (accuracy), solver iterations, and global mesh resolution, all stored in the document

---

## Requirements

| Requirement | Version |
|---|---|
| FreeCAD | 1.0 or later |
| Python | 3.x (bundled with FreeCAD) |
| pybullet | any recent version |

---

## Installation

### 1 — Install pybullet

pybullet must be available to the Python interpreter bundled with FreeCAD.

```bash
python3 -m pip install pybullet
```

On some Linux distributions where the system enforces package isolation you may need:

```bash
python3 -m pip install pybullet --break-system-packages
```

If you are on GCC 15+ and the build fails with `-Werror=return-type`, use:

```bash
CFLAGS='-Wno-error=return-type' CXXFLAGS='-Wno-error=return-type' \
  python3 -m pip install pybullet --break-system-packages
```

### 2 — Install the workbench

**Option A — FreeCAD Addon Manager (recommended once listed)**

Open FreeCAD → Tools → Addon Manager → search for **Bullet Physics** → Install.

**Option B — Manual**

Clone this repository into your FreeCAD `Mod` folder:

```bash
# Linux / macOS
cd ~/.local/share/FreeCAD/Mod        # FreeCAD 1.x path
# or ~/.FreeCAD/Mod for older versions
git clone https://github.com/kevinsmia1939/FreeCAD-BulletPhysics

# Windows
cd %APPDATA%\FreeCAD\Mod
git clone https://github.com/kevinsmia1939/FreeCAD-BulletPhysics
```

Restart FreeCAD and select **Bullet Physics** from the workbench dropdown.

---

## Quick Start

1. Open or create a FreeCAD document containing at least one solid.
2. Switch to the **Bullet Physics** workbench.
3. Click **Create Physics Container** — this adds a *Bullet Physics* folder to the model tree containing a *Physics World* settings object and a *Rigid Body Summary* table.
4. Select a solid in the 3D view, then click **Add Active Body** (moves with physics) or **Add Passive Body** (static collider).
5. Repeat step 4 for each solid you want to simulate.
6. Adjust physics properties in the **Physics World** object (gravity, end time, time step, etc.) and per-body properties (density, friction, restitution) via the model tree or the Rigid Body Summary table.
7. Click **Run Simulation** in the toolbar to open the simulation panel.
8. Click **Simulate** — a progress bar tracks the run. When it finishes the timeline slider is enabled.
9. Drag the slider or press **Play** to watch the animation.

---

## Physics World Settings

| Property | Default | Description |
|---|---|---|
| **Gravity** | 9.81 m/s² | Gravitational acceleration magnitude |
| **GravityDirection** | (0, 0, −1) | Direction vector for gravity (−Z = downward) |
| **EndTime** | 10.0 s | Total simulation duration; timeline runs 0 → EndTime |
| **TimeStep** | 1/60 s | Duration of each recorded frame (controls playback FPS) |
| **SubSteps** | 4 | Bullet ticks per frame — higher values improve collision accuracy without changing playback speed or total duration |
| **SolverIterations** | 10 | Constraint-solver iterations per tick — higher values improve stacking stability |
| **MeshResolution** | 1.0 mm | Tessellation chord deviation for custom mesh collision shapes — smaller = finer mesh (global default; can be overridden per body) |

---

## Rigid Body Properties

| Property | Default | Description |
|---|---|---|
| **BodyType** | Active | *Active*: moved by physics. *Passive*: static collider |
| **Density** | 1000 kg/m³ | Material density; mass is computed automatically as density × shape volume |
| **Restitution** | 0.3 | Bounciness — 0 = no bounce, 1 = perfectly elastic |
| **Friction** | 0.5 | Coulomb friction coefficient |
| **MeshResolution** | 0 mm | Per-body tessellation override — 0 = use Physics World default |

---

## Simulation Panel

| Control | Description |
|---|---|
| **Simulate** | Run the simulation using current Physics World settings |
| **Timeline slider** | Scrub to any frame |
| **Transport buttons** | First / step back / play-pause / step forward / last |
| **Speed** | Playback speed multiplier (0.1× – 8×) |
| **Loop** | Loop playback when it reaches the end |
| **Reset to Initial Position** | Restore all links to their pre-simulation placements |
| **Bake Frame as New Origin** | Copy the current frame's placements to the original objects (undoable with Ctrl+Z); clears the cache so you can re-simulate from this pose |
| **Delete Cache** | Remove the simulation cache file from disk |

---

## How It Works

```
OriginalObject (your solid)          ← never moved, full CAD history intact
       │
       └─► App::Link (BodyLink)      ← simulation drives this clone
```

The workbench tessellates or analytically describes each solid for pybullet, runs the simulation in headless (`DIRECT`) mode, records a `Placement` for every active body at each frame, and plays them back by updating the `App::Link` placements.

The recorded frames are serialised as JSON to `<document>_bullet_cache.json` alongside your `.FCStd` file so they survive closing and reopening the simulation panel.

---

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
