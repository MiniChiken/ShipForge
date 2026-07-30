# ShipForge — making your first ship

A walkthrough from a model file to a flyable ship. Assumes the repo is set up as
described in the main [README](../README.md) (an EVE client, an EvEJS server,
Blender, and the native authoring kit in `kit/`).

```bash
python shipforge/server.py --open        # http://127.0.0.1:8770
```

---

## 1. What ShipForge expects of a model

Read this before importing. Most first-run problems are the model, not the tool.

### Format

Any of `.blend`, `.obj`, `.glb` / `.gltf`, `.fbx`, `.stl`, `.dae`. Blender does
the import, so anything Blender opens will work.

### Requirements

| | |
|---|---|
| **Scale** | Doesn't matter. You give a target length in metres and everything is scaled to it. EVE battleships run roughly 900–1500 m; a value far outside that will look wrong next to stock ships. |
| **Orientation** | **The nose must point along Blender −Y, and +Z must be up.** This is the one thing ShipForge cannot infer. Get it wrong and the ship flies backwards or on its side. |
| **Origin** | Doesn't matter. The frame is centred on the mesh's own bounding box. |
| **Topology** | Triangles or quads. It gets joined and decimated into a LOD chain, so N-gons and loose geometry are tolerated but will decimate unpredictably. |
| **Vertex count** | 32-bit indices are supported, so there is no 65,535 ceiling. The reference Venator is ~135k triangles across 75,627 vertices. |
| **Materials** | Needed for auto-detection. See below. |
| **Solid hull** | Locators are placed by raycasting **down** onto the hull. Holes in the surface make a locator fall through — ShipForge flags this, but a watertight upper surface saves work. |

### Materials earn you automation

Nothing here is required, but each one turns a manual job into a button:

* **A material named for the engine glow** (e.g. `Thruster Glow`) on the *nozzle
  exit faces* — enables **Auto-detect nozzles**. It selects by material, clusters
  the faces into discrete discs, and keeps only those whose mean normal faces
  **astern**, so vents and manoeuvring thrusters are rejected.
* **A material with `window`, `glow`, `light` or `lamp` in the name** — used to
  build the emissive map, so the ship has lit windows instead of a dead hull.
* **Separate objects for decorative turrets**, named with a common prefix — set
  that prefix as `ignoreNamePrefix` so they don't block surface raycasts. Note
  that stock EVE hulls model *mounting plates, not guns*: EVE mounts its own
  functional turrets at your locators, so sculpted guns will intersect them.

### One trap worth understanding

**Do all your measuring and your geometry export from the same blend.** The
coordinate frame is centred on the mesh bounding box, and a rotated object's
transformed local bbox *overstates* its extent — so a scene of many separate
objects produces a bigger box than the same mesh joined, and therefore a
different frame.

On the reference ship this bit hard: identical 75,627 vertices gave
`Y −125.954..+125.954` joined and `Y −106.111..+145.797` unjoined, a pure
**19.843 m** shift. The geometry was exported from one blend and the locators
measured in the other, so every locator sat 19.843 m above the hull and turrets
looked like they were floating. `compare_frames.py` shows this for any two blends.
The probe now derives the frame from **vertices**, which is stable across both,
but the lesson stands: if you swap blends mid-project, re-measure.

---

## 2. Create the project

1. Type a name in the header box and press **Create**. It becomes the SOF hull
   name (`<name>_t1`) and the resource namespace (`res:/elysian/ships/<name>`).
2. On the **Geometry** tab, set the model path and the target length in metres.
3. Press **Import / probe**.

This takes a minute or two — it raycasts a height field over the whole hull. When
it finishes, the three views fill with the model and the header reports vertex
count and measured extents.

Sanity-check the extents before continuing. If X and Z look swapped, or Y spans
the length of the ship, the model's orientation is wrong; fix it in Blender and
re-import.

---

## 3. Shield volume — Geometry tab

Press **Fit to hull**.

Do not hand-type the half-extents. Radii equal to the hull's half-extents do
**not** enclose it — they only touch the six face centres, and everything else
pokes out. Fit finds the smallest uniform inflation that puts every vertex
inside; on the reference ship that is 1.23×. It centres on the origin, as stock
hulls do, because centring on the bounding box rides high on any hull whose mass
sits below its superstructure.

---

## 4. Placement tab

### Turrets

**Add pair** creates a hardpoint with a port (`a`) and starboard (`b`) locator.
Drag them in the top view for X/Z and the side view for Y, then **Snap all to
hull** to sit them on the surface exactly.

Three rules the tool enforces or warns about:

* The **digits** in the name are the hardpoint. `1a` and `1b` are two mounting
  positions of *one* gun; the client renders both and fires whichever has line of
  fire. That is where the stock "only the side facing the target shoots"
  behaviour comes from.
* `a` is **port** (−X) and `b` is **starboard** (+X), on every stock hull checked.
* **`hiSlots` must equal the number of hardpoints.** The client maps a fitted
  turret to `locator_turret_<high slot index + 1>`, so a turret in a high slot
  with no matching group renders nothing. The pill next to the Turrets heading
  goes red when they disagree.

Snapping runs a real raycast, not the height field — the field's cells are
several metres across and on a stepped hull the nearest one can sit on the deck
beside the pocket a locator belongs in. A locator with **no hull beneath it** is
flagged; either move it or accept that its twin's mirrored value will be used.

### Boosters

**Auto-detect nozzles** if the model has an engine-glow material. Otherwise place
them by hand on the nozzle exits.

Plume length is a ratio of nozzle radius; stock hulls run about **14** and the
tool warns outside 8–20. Too small renders a stubby cone that reads as a flat
disc rather than an exhaust trail.

### Lights

**Nav lights from anchors** places running lights on the measured silhouette
extremes — wingtips, bow, tower, stern.

Spotlights are more delicate. Aiming one along the hull's surface normal points
it *straight up*, which renders as a vertical light shaft rather than a pool on
the deck. Bow lights aimed forward work well; deck floods generally do not.

---

## 5. Attributes tab

**Pick a donor hull first.** It decides three things at once:

* the **hull bonuses** — these live in the donor's `dogmaEffects` and are bespoke
  per ship, so there is no way to graft a bonus from elsewhere. The only way to
  get projectile bonuses is to clone a projectile ship.
* how many bonuses the ship can have — the slot count is fixed by the donor.
  Slots can be swapped, not added.
* which **attributes are editable** — one the donor doesn't carry cannot be
  added, because an FSD insert must byte-match an existing record.

Search by effect (e.g. `projectile`) to find candidates; the list shows each
one's bonus count. Bonuses are rendered in plain English, so you can read
"+10% Damage Multiplier on modules requiring Large Projectile Turret per skill
level" rather than `shipPTdamageBonusMB2`.

Then edit statistics by clicking a row. Overrides show in gold; blank the value
to return to the donor's.

**The SOF faction is separate from the donor, and it decides how bright your ship
looks.** The faction supplies the four materials the `_m` map selects between:
`amarrbase` band 1 is `white_ivory_matt`, `minmatarbase` band 1 is
`black_gunmetal_brushed`. A hull with most of its surface on band 1 renders
almost black under the wrong faction, and no albedo value compensates. Pick the
donor for its dogma, then set the faction for the look.

---

## 6. Preview, build, deploy

| button | what it touches |
|---|---|
| **Build hull** | Nothing live. Authors the SOF hull into `native_out/`. |
| **Preview in Trinity** | Publishes `data.black` only, then renders in the client's own engine. No FSD, no server, no dogma. `revert_preview` restores the index row. |
| **Deploy** | Publishes resources. Applies FSD **only if** its inputs changed. |
| **Verify live** | Reads the hull back out of the published file and reports per-field. |

Preview and Build rebuild automatically if the hull on disk doesn't match the
project, so an edit can't silently fail to appear.

Deploy needs the client **closed** only when FSD changes — that means a stat or
bonus edit, or a new donor. Placement and texture changes are resource-only and
can be deployed with the client running; restart it to see them.

After any deploy, **kill and relaunch the client**. A relog is not enough: the
resource index is read once at process start.

### If the client dies at character select

`TypeNotFoundException` naming your typeID means the FSD bundle is rolled back
and the ship's type does not exist. Recover with:

```bash
python fsd_deploy.py apply
```

then republish resources — a rollback reverts them. Deploy checks for this and
refuses to report success while the typeID is missing from the live tables.
