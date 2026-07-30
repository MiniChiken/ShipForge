# ShipForge — adding a genuinely new ship to EVE Offline (EVE V24.01)

Tooling for putting a custom ship into the EVE client running against a local
[EvEJS](https://github.com/rrfarmer/EveOffline) server — as a **new ship**, not a
reskin. New typeID, new graphicID, new hull definition, its own geometry, textures,
name, description, icon and locators. **Nothing existing is overwritten.**

Two halves:

* **`shipforge/`** — a local editor ([section 8](#8-shipforge--the-setup-editor)) for
  placing shield volume, turret hardpoints, boosters and lights against the model,
  previewing the result in EVE's own renderer, and building/deploying it.
* **everything else** — the format readers and writers, authoring workers and deploy
  scripts the editor drives, documented below. They also work standalone.

The reference ship is a Star Wars Venator-class Star Destroyer, but nothing here is
specific to it beyond the example project.

**Status: working in-client.** typeID `900001`, graphicID `900001`, SOF hull
`venator_t1`. Flyable, fittable, named, with its own stats.

This document is the pipeline as it actually stands, plus the reasoning behind the
parts that are easy to get wrong. An earlier revision of this file concluded that a
new ship was *impossible*; [section 9](#9-corrections-to-earlier-conclusions) explains
why that was wrong, because the mistake is more instructive than the fix.

---

## 0. What is and isn't in this repo

**Tooling and documentation only.** Deliberately excluded:

* **The source model** — the Venator `.blend` and its textures are Lucasfilm/Disney
  IP. Supply your own and point the scripts at it.
* **Decompiled EVE client Python** and any extracted or derived game assets —
  `.gr2`, `.dds`, `.black`, atlases, icons. CCP's content, or reproducible locally.
* **`liboodle`** — public domain, but a third-party repo:
  `git clone https://github.com/LunaticInAHat/liboodle ref`

Nothing here ships game content. The scripts read an EVE installation you already have
and write into your own local client.

Worked out against **EVE V24.01 build 3396210** on a private, offline server. Not
intended for, and never tested against, live Tranquility.

---

## 1. The central insight

The formats that matter — SOF `.black`, cFSD `.fsdbinary`, the localization pickles —
are schema-driven, and the schemas are compiled into the client's own binaries rather
than described in the files.

The first attempt read that as a wall: *the schema is inside `_trinity_dx11.dll`, so
the file cannot be written.* The correct reading is the opposite:

> **The DLL that owns the schema can write the file for you.**

The client ships a Python 2.7 interpreter and its own loaders. Run code *inside* the
client and every format becomes readable and writable through the same code paths the
game uses:

```bash
exefile.exe /py <script.py> <args...> /inherit
```

```python
import blue
import _trinity_dx11          # REQUIRED - registers the trinity.* classes.
                              # Without it LoadObject cannot deserialize an
                              # EveSOFDataHull and silently returns None.

hull = blue.resMan.LoadObject("res:/dx9/model/spaceobjectfactory/hulls/mb3_t1.black")
hull.name = "venator_t1"
blue.resMan.SaveObject(hull, out_path)
```

Everything else here follows from that. The same trick supplies a Python 2.7 compiler
(`py27c.exe` loads `tq/bin64/python27.dll`) and a stand-in `python.exe`
(`py27shim.exe`) for tools that shell out to one.

---

## 2. How resources reach the client

`tq/resfileindex.txt` maps `res:/...` paths to blobs in `ResFiles/`, read **once at
process startup**. Blobs are stored uncompressed, so publishing is: write the blob,
rewrite the index line.

```
res:/path,<aa>/<pathhash>_<md5>,<md5>,<size>,<compressed_size>
```

```bash
python install.py --publish "res:/elysian/ships/venator/venator_t1.gr2" venator_t1.gr2
python install.py --revert
```

Three things that cost real time:

* **A relog is not enough.** The index is read at process start. Logging out to
  character select and back serves the *old* build. Kill and relaunch. Verify with
  `Get-Process exefile | Select-Object Id,StartTime` — if `StartTime` predates the
  publish, you are not looking at your work.
* **New `res:` paths CAN be minted.** The `<pathhash>` prefix is **opaque**: the client
  does not recompute or verify it, it just follows the mapping. Any deterministic
  allocator works. `install.py` uses `sha256(lowercased logical path)[:16]`. This is
  what makes a new ship possible at all — new geometry, textures and icons all live at
  new paths.
* **Publishing order matters.** See [section 7](#7-deployment-order).

---

## 3. Geometry

```
.blend --Blender--> venator_lod.{bin,json} --build_venator_lod.py--> .gr2 --publish--> client
```

**Axis transform — get this right first.** Blender `(x, y, z)` -> EVE `(x, z, -y)`:
a proper -90 degree rotation about X (determinant **+1**).

> `(x, z, y)` is a **reflection** (det -1) and produces three symptoms that look
> unrelated: the ship is **mirrored**, the **exhaust appears at the nose**, and **every
> triangle's winding inverts** (hull renders inside-out or invisible). With a proper
> rotation the source winding is already correct — do **not** also reverse indices.

EVE orientation: **+Z is forward** (nose), **+Y is up**, stern at -Z. Scale is
**1 model unit ~= 1 metre**, measured across 8 stock battleships (ratio 0.85–1.11).
`ArtToolInfo.UnitsPerMeter = 100` is vestigial Maya metadata, not world scale.

A hull must mirror the hull it is modelled on structurally:

| field | requirement |
|---|---|
| vertex format | **per-hull** — read it from the donor |
| meshes | 7: `<Shape>` plus its own LOD ladder |
| `Materials` | **empty** — materials come from SOF |
| `Skeletons` | 1 root bone named for the hull |
| `BoneBindings` | **1 per mesh**, bone name + OBB — without this the mesh renders **invisible** |
| triangle groups | count == the hull's SOF opaque-area count, bound by index |
| root arrays | stock registers only **1** `VertexData`/`TriTopology` despite 7 meshes |

`diff_hull.py` compares a build against a stock hull field-by-field. **Run it before
every client test** — it found the missing bone bindings and the root-array mismatch in
one pass, after several client restarts had been spent guessing one variable at a time.

---

## 4. The hull definition (SOF)

Per-hull `hulls/*.black` files are **ignored by the client** — hull definitions come
only from the 180 MB `res:/dx9/model/spaceobjectfactory/data.black`. Proven by
experiment: repointing the Armageddon's per-hull texture strings changed nothing.

`author_venator.py` runs inside the client, loads a donor hull, edits it, and **appends**
it to `data.black`'s hull array (2538 -> 2539). It is idempotent — re-authoring replaces
the existing entry in place rather than appending a duplicate.

Textures are retargeted **in place by slot name**, so each area's shader and parameter
objects survive byte-for-byte; only `resFilePath` changes.

### 4.1 Turret locators

Read out of the client's own `turretSet.pyj` and confirmed against four stock hulls.
Getting these wrong accounts for more wasted client restarts than anything else.

```python
locatorSets = {filter(str.isdigit, loc.name) for loc in locators}
return len(locatorSets)
```

* **The DIGITS are the hardpoint.** `locator_turret_1a` and `1b` are two *mounting
  positions of one gun*. The client renders both and fires whichever has line of
  fire — this is the stock "only the side facing the target shoots" behaviour.
* **`a` is port (-X), `b` is starboard (+X)**, on every pair of every hull checked.
  Top/bottom pairs use the same scheme vertically.
* **A fitted turret maps to `locator_turret_<high slot index + 1>`**
  (`GetSlotFromModuleFlagID`). So **`hiSlots` must equal the number of locator
  groups** — with 5 high slots and 4 groups, a turret in the last high slot resolves
  to `locator_turret_5*`, finds nothing, and renders no gun.
* **The transform carries orientation, not just position.** Rows are
  (localX, localY, localZ); **localY is the mount normal** and
  **localX = localY x localZ**. Verified against `ab2_t1`'s `1a` (localY = -X,
  outboard to port), `1b` (+X) and the identity case used for centreline dorsal
  mounts. Identity everywhere leaves port and starboard indistinguishable.
* **Place the locator at the hull SURFACE.** EVE mounts the turret graphic
  pivot-at-base; a locator at the turret mesh's centroid lifts the gun half its own
  height off the deck. Raycast down onto the hull rather than trusting the mesh —
  one Venator mount has a hole under it, where the ray falls through and reports the
  underside 87 m below.

### 4.2 Boosters

* Positions are the emissive nozzle-exit discs. Select them by **material**, cluster
  spatially, and **check the mean face normal** — a real nozzle faces astern, while
  manoeuvring thrusters and vents share the same emissive material and face up or
  outboard. Dressing those as boosters puts exhaust high on the hull.
* **Plume length is a ratio.** Stock hulls run Z-scale ~= **14x** the XY scale
  (`ab2_t1` 14–18, `gb1_t1` 13.5–14.7, `mb3_t1` 10–15). Too small renders a stubby
  cone that reads as a flat disc rather than a trail.
* `lightScale` is **1.0** on every stock booster.

### 4.3 Bounding volumes

`shapeEllipsoidCenter` / `shapeEllipsoidRadius` drive the shield bubble.

* **Radii equal to the hull's half-extents do NOT enclose it** — they only touch the
  six face centres. The Venator tested `(273/285)^2 + (126/140)^2 = 1.72` at a wingtip
  and the shield cut straight through the model. `fit_ellipsoid.py` finds the smallest
  uniform inflation that puts every vertex inside: **1.23x** here.
* **Centre on the origin, not the bounding box.** The bbox centre sat at Y +19.8
  because the thin conning tower reaches +146 while the hull's bulk is at mean
  Y -24 — a volume centred there visibly rides high on the model. Origin-centred both
  looks right and needs *less* inflation (1.23x against 1.32x).
* Measure extents from **vertices**, not object bounding-box corners: a rotated
  object's transformed local bbox overstates its extent.

---

## 5. Client static data (FSD)

Three cFSD tables need rows: `graphicids`, `types`, `typedogma`. Patched with the
Elysian FSD toolkit, which compiles tables and verifies each one through a native
probe.

* **All changes go in ONE change set.** The per-table proofs are bound to the pristine
  table MD5s, so once a bundle is applied the compiler gate refuses further edits
  (*"mutation verification has not passed"*). Roll back to baseline and re-apply the
  complete set rather than layering a second bundle.
* **An INSERT's value must exactly equal an existing record.** The compiler clones that
  record's bytes and rekeys it; every field difference is a follow-up UPDATE.
* **UPDATE paths accept integers**, so nested list entries are reachable —
  `("dogmaAttributes", index, "value")` patches one attribute without rewriting the
  list.
* The probe needs a Python 2.7 interpreter installed as
  `tools/.elysian-suite/runtime/python27/python.exe` — `py27shim.exe` forwards to
  `exefile.exe /py`.
* An **operation lock** prevents two runs touching the client at once. If you see
  `TargetBusyError`, another run is live — wait for it. Do not kill a running `apply`;
  it is mid-write on client resources.

### 5.1 Choosing a donor hull

**Ship bonuses live in bespoke per-hull `dogmaEffects`.** Comparing
Rifter / Rupture / Tempest / Maelstrom / Hurricane against
Raven / Megathron / Armageddon / Typhoon shows **no shared "projectile bonus" effect**
to graft on. Projectile bonuses can therefore only come from cloning a projectile
hull. Pick the donor for the *bonuses and race* you want, then patch slots and stats
on top. The Venator clones the **Maelstrom** (Minmatar, large projectile damage +
shield boost) and overrides layout and tank.

**But a graphicID clone also brings its SOF FACTION, and the faction decides which
materials the `_m` map selects.** This is a trap worth stating plainly, because it
looks exactly like a texture problem and is not one. Each faction supplies four
`Primary` area materials:

| slot | amarrbase | minmatarbase |
|---|---|---|
| material1 | `white_ivory_matt` | `black_gunmetal_brushed` |
| material2 | `grey_steel_brushed` | `grey_darksteel_brushed` |
| material3 | `black_gunmetal_metallic` | `blue_bluedsteel_metallic` |
| material4 | `gold_true_polished` | `brown_rust_matt` |

The Venator's `_m` map puts ~93% of the hull on band 1. Tuned under the Armageddon's
graphicID that band was `white_ivory_matt`; switching the donor to the Maelstrom
silently made it `black_gunmetal_brushed`, and the whole ship rendered as black
gunmetal. Raising the albedo from mean 131 to the stock 199 barely moved it, because
the tint, not the texture, was the problem.

So: **choose the donor for its dogma, then set `sofFactionName` for the look you
want.** They are independent - `sofFactionName` / `sofRaceName` are fields on the
graphicID record, and the bonuses live in `typedogma`. The Venator ships
`amarrbase` / `amarr` for a light grey hull with Minmatar projectile bonuses.
`faction.materialUsageMtl1..4` additionally permutes the bands per faction
(amarrbase `2,1,0,3`, minmatarbase `0,1,2,3`).

### 5.2 Icons

Icons resolve as **`graphicids[gid].iconInfo.folder` + `/<graphicID>_<size>`**, e.g.
`res:/dx9/model/ship/minmatar/battleship/mb3/icons/3134_64.png`. The shipped set is
`_64.png`, `_128.png`, `_512.jpg`. Cloning a donor graphicID inherits *its* folder, so
the client looks for `<yourGraphicID>_64.png` in a stock folder that has no such file
and shows nothing. Repoint `iconInfo.folder` at your own namespace and publish there.

---

## 5.3 Trait text (the Info panel's bonus list)

The bonus list in a ship's Information window is **not** in the cFSD tables, so a
ship with perfectly good `dogmaEffects` still shows nothing. `traits.pyj` asks:

```python
def has_traits(ship_type_id):
    return ship_type_id in get_info_bubble_type_bonuses()
```

and that mapping is `res:/staticdata/infobubbles.static`, key
`infoBubbleTypeBonuses`. An absent typeID renders an empty panel.

**`.static` files are plain SQLite** — `cache(key TEXT, value TEXT, time FLOAT)`
with JSON in `value` — so stdlib `sqlite3` and `json` are enough; nothing has to
run inside the client. (`fsdlite/encoder.py` confirms the payload is yaml/ujson;
`.static` is its SQLite cache.) The first 16 bytes read `SQLite format 3`, which
is worth checking before building machinery to open a file.

Entry shape per typeID:

```json
{"types": {"<skillTypeID>": [{"bonus", "importance", "nameID", "unitID"}]},
 "roleBonuses": [...], "miscBonuses": []}
```

`nameID` is a localization message, so cloning the DONOR's entry gives text that
matches the bonuses the ship actually has - it carries the donor's effects.
`patch_infobubbles.py` does this.

---

## 5.4 Going back to vanilla

ShipForge's **Vanilla** button returns the client and server to stock and
**destroys nothing**:

* a publish never deletes a blob - every custom resource stays on disk under its
  own md5
* `install.py --revert` restores `resfileindex.txt` from the backup taken before
  the first publish, undoing every republished stock resource in one step
* the project, the built hull and the FSD bundle all remain

so **Deploy re-enables the ship**. A `<hull>.vanilla.json` records what was
disabled.

**It refuses while anything still owns the ship.** Going vanilla removes the
typeID, so a surviving item references a type the client cannot resolve and
character select fails with `TypeNotFoundException`. The check reads the items
table in the server's `gamestore.sqlite` - **not** `characters/data.json`, which
lags: it reported Capsule 670 for a pilot whose items table already held the
custom ship. It also requires the client closed. There is an override, but using
it while the ship is owned will break the client.

---

## 6. Name, description, stats

* **Localization.** `loc_worker.py` appends message IDs to all 10
  `localization_fsd_<lang>.pickle` files, then `types.typeNameID` /
  `descriptionID` point at them. Must run under the client's **own Python 2.7**: a
  Python 3 re-pickle emits `_codecs.encode` globals and the client dies at startup with
  `UnpicklingError: _codecs.encode not in whitelist`. Preserve the shipped protocol —
  forcing protocol 0 inflates these files enormously. Rebuild from pristine sources
  each run so it stays idempotent.
* **Server stats.** `server_patch.py` updates `shipTypes`, `itemTypes` and `typeDogma`
  in the EvEJS container. `itemTypes` is what the GM `/item` command resolves against —
  `shipTypes` alone will not spawn one.
* **The client keeps its own `typedogma`**, and the fitting window and HP bars read
  from *that*, not the server. Without a client row, max HP resolves to 0 (the hull
  renders destroyed) and there are no module slots. Both sides must agree.

---

## 7. Deployment order

**This is the single most expensive lesson in the project.**

An FSD bundle apply or rollback **replaces the entire `resfileindex.txt`**, not just
the rows for the tables it owns. `prepare_fsd_bundle` renders the whole index as it
existed at *prepare* time and stages it as an artifact; apply installs it, rollback
restores the pre-apply copy. **Any resource published in between is silently
reverted** — while `install.py` still reports success.

This cost a full debug cycle: a corrected hull was published, an unrelated rollback ran,
and the client kept serving the old hull. It looked exactly like an authoring failure.

```
1. fsd_deploy.py rollback      # back to pristine tables
2. fsd_deploy.py apply         # one combined change set
3. install.py --publish ...    # hull, localization, icons - ALWAYS LAST
4. docker restart <server>     # server caches static tables at boot
```

`finish_deploy.py` encodes this order. Then **start the client fresh**.

> When a change "doesn't take", diff the live index row against the file you built
> before re-authoring anything:
> `Select-String -Path tq\resfileindex.txt -Pattern '^res:/<path>,'` versus
> `Get-FileHash <built file> -Algorithm MD5`.

**Be docked before deploying.** Step 4 restarts the server out from under a logged-in
client, which presents as "server not responding" on undock.

### Verifying, not assuming

Every stage can be read back through the client's own loaders, and should be:

| script | checks |
|---|---|
| `probe_hull.py` | the LIVE hull from the published `data.black` — locators, boosters, bounds |
| `probe_template.py` | stock hulls, for convention (this is how the locator rules were found) |
| `verify_fsd.py` | the LIVE patched FSD tables against the intended values |

`verify_fsd.py` deliberately exports to `fsd_verify/` rather than `fsd_export/`, which
is the pristine baseline the change sets are built against.

---

## 8. ShipForge — the setup editor

Everything above was originally tuned by hand: guess a number, rebuild the hull,
redeploy, restart the client, look at it in game, repeat. ShipForge collapses that to
one pass, and makes the *next* ship cheap.

```bash
python shipforge/server.py --open        # http://127.0.0.1:8770
python shipforge/seed_venator.py         # seed a project from an existing build
```

**New to it? Start with [shipforge/GETTING-STARTED.md](shipforge/GETTING-STARTED.md)** —
a walkthrough from a model file to a flyable ship, including what ShipForge
expects of a model (nose along Blender -Y, +Z up; materials that unlock the
auto-detection) and the traps that are worth knowing before the first import.

Standard library only, nothing to install. Long steps (a Blender probe, authoring
inside the client, a deploy) run as background jobs whose log the UI tails.

### Workflow

1. **Import** a model (blend/OBJ/GLB/FBX/STL/DAE). `blender_probe.py` returns the
   vertices, measured extents, materials, emissive nozzle discs, silhouette anchors,
   an enclosing-ellipsoid fit, and a height+normal field over the XZ plane.
2. **Place** locators in three orthographic views (top / side / front). Turret X/Z
   comes from the top view, Y from the side. Wheel zooms about the cursor,
   middle-drag pans, double-click resets a panel. Ctrl+click toggles, Shift+click
   extends, dragging empty space box-selects, and dragging any selected handle
   **moves the whole group by one delta**, so relative spacing is preserved exactly.
   Numeric fields sit alongside, because exact values matter as much as eyeballing.
3. **Assist** with the measurements that are easy to get wrong:
   * snap to the hull surface, and flag locators with no hull beneath them
   * auto-detect engine nozzles by material **and aft-facing normal**
   * fit the shield ellipsoid with the inflation that actually encloses the hull
4. **Preview in Trinity** - render the authored hull through the client's own
   renderer, with real turret hardpoint mounting and boosters. See 8.1.
5. **Build** - native `.black` authoring via the workers above.
6. **Deploy** - FSD apply then publish, in that order, server restart opt-in.
7. **Verify** - reads the hull back out of the *published* `data.black` and reports
   pass/fail per field, rather than trusting that a command exited 0.

### Snapping uses an exact raycast, not the height field

The probe's field has ~4m cells. Fine for live feedback, wrong to snap with: on a
stepped hull the nearest cell can sit on the deck beside the pocket a locator belongs
in. Measured on the Venator, grid samples disagreed with an exact raycast at the same
coordinates by **4 to 9 metres**. So `blender_snap.py` raycasts the real geometry at
the real coordinates, and the field is display-only.

### Constraints it enforces by construction

So they cannot drift, each having cost a debugging cycle:

* `hiSlots` == number of turret locator groups
* turret groups are the digits; `a`/`b` are port/starboard positions of one hardpoint
* locator rows are (localX, localY, localZ), localY = mount normal, localX = Y x Z
* booster plume Z:XY ~= 14 (warns outside 8-20), `lightScale` 1.0
* shield radii never smaller than the hull's half-extents
* resource publishes strictly **after** the FSD apply

`Build`, `Preview` and `Deploy` stay separate actions.

### The deploy safety model

An FSD apply is a **rollback followed by a multi-minute compile**. If anything
fails in between, the client's tables are left pristine: the ship's typeID does
not exist, and the only symptom is the client dying at character select with

```
characterSlots.py(1310) LoadInfo
TypeNotFoundException: 'key not found'   typeID = 900001
```

which says nothing about FSD and reads as a broken login. That happened twice
before the following guards existed, so they are not hypothetical:

* **FSD is skipped unless its inputs changed.** `fsd="auto"` fingerprints the
  project's FSD fields *and `fsd_insert.py`'s own source* - that module, not the
  project, holds the donor typeIDs and the slot/tank values, so editing it is a
  real change. A locator nudge therefore never touches the static tables.
* **A stale build is never published.** `Build` stamps the artifact with a
  sha256 of the authoring request; `Deploy` compares it against the project and
  builds first when they differ. Without this, editing and hitting Deploy
  without Build shipped the *previous* hull while every step reported success.
* **`client_running()` fails safe.** An unanswerable process check reports
  "running". Treating it as "closed" let a deploy roll the bundle back and only
  then hit the suite's own client check.
* **A failed apply retries once.** The tables are pristine at that point, which
  is exactly what a fresh apply needs. Only a second failure raises, naming the
  recovery command.
* **Deploy will not claim success unless the typeID is in the live tables.** It
  re-exports the tables the resfileindex currently points at and checks all
  three.
* **Only an FSD change needs the client closed.** It rewrites files the client
  holds open. A resource publish writes a blob and one index line, which a
  running client neither reads nor locks, so placement changes deploy live and
  appear on the next restart.

Recovering by hand, if it ever does strand:

```bash
python fsd_deploy.py apply        # restores the typeID
# then republish every resource - the rollback reverted them
```

`finish_deploy.py` republishes `data.black`, localization and icons but **not**
the texture DDS files. Use ShipForge's Deploy, whose project `extraResources`
tracks all of them, or an FSD cycle will silently revert texture work.

### 8.1 Trinity preview

[Elysian Jessica - Trinity Viewer](https://github.com/JohnElysian/Eve-Online-Trinity-Viewer)
(MIT) renders EVE assets through the installed client's native Blue/Trinity stack. Its
entry point takes a SOF DNA directly:

```
trinity_live_viewer.py TYPE_ID DNA RADIUS WIDTH HEIGHT [MODE] [CATALOG_JSON] [COMMAND_JSONL]
```

so a hull can be previewed with no catalogue entry for it. DNA is
`<hull>:<faction>:<race>`, e.g. `venator_t1:amarrbase:amarr`. ShipForge launches it
through `exefile.exe /py`, the same mechanism as the authoring workers.

Clone the viewer to `C:\evejs\tools\trinity-viewer`, or set `SHIPFORGE_VIEWER`.

Two things worth knowing. Trinity resolves a hull through the client's resource
system, so Preview **publishes `data.black`** - that one resource and nothing else: no
FSD tables, no server, no type or dogma change, and `install.py` keeps its index
backup. And because the DNA is passed directly, a hull can be previewed under a
*different faction* than its graphicID currently names - which is how the
`minmatarbase` -> `amarrbase` material problem in section 5.1 can be confirmed before
deploying it.

---

## 9. Corrections to earlier conclusions

An earlier version of this document reported three blockers. All three were wrong, and
the pattern in the mistakes is worth recording.

| earlier claim | reality |
|---|---|
| `data.black` cannot be written — its schema is compiled into `_trinity_dx11.dll` | That DLL **writes the file for you**. Run inside the client and use `blue.resMan.SaveObject`. |
| New `res:` paths cannot be minted — the path hash is not derivable | The prefix is **never verified**. The client follows the index mapping; any deterministic allocator works. |
| A genuinely new ship is impossible — a graphicID must name a hull, and hulls come only from `data.black` | True premise, wrong conclusion: **append a new hull** to `data.black`. |

Two failures of reasoning produced all three:

1. **Treating "I cannot parse this format" as "this format cannot be written."** The
   goal was never to understand the bytes — it was to change the data. The client
   already had code that does both.
2. **Failing to generalise a solution already in hand.** The Python 2.7 problem had
   already been solved by loading the client's own `python27.dll`. The identical move
   applies to `_trinity_dx11.dll`, and it went unnoticed for a long time.

Reverse-engineering the container formats was still necessary — `.gr2` had to be
*written* from scratch, and `granny.py` / `gr2write.py` / `oodle1.py` all stand. But
the wall was never technical.

### Still open

* **BitKnit2** (Granny section compression 4) has no public reverse-engineering.
  Modern hulls using it cannot be read. Workaround: a hull's vertex format lives at
  `sec6+0`, sec6 is small and usually decodes even when sec0 fails, and the format can
  be recovered structurally without sec0's name strings.
* **Oodle1** faults partway through very large multi-stream sections. Small and
  single-stream sections are solid.
* **The hull mesh still carries its own sculpted turrets.** EVE mounts functional
  turrets at the locators, so the two intersect. Stock hulls model mounting plates,
  not guns, so the decorative geometry (the `Venator.*` objects here) should be
  excluded from the geometry export - which means a `.gr2` rebuild, not just a
  re-author.
* **Spotlights aimed along the surface normal point straight up** and render as
  vertical light shafts rather than pools on the deck. The eight deck floods were
  removed for that reason; only the bow pair remains. Deck lighting that reads
  correctly needs a different aim, not a different intensity.
* **Hull lighting** — the remaining SOF fields (`planeSets`, `hazeSets`,
  `decalSets`) have not been surveyed. The hull still carries the Armageddon
  donor's `forcefield` planes at its coordinates, `(0, -83, +375)`.
* **`fighterTubes` / `fighterCapacity`** are set server-side but not yet mirrored into
  the client's `typedogma`.
* **What rolled the FSD bundle back** on one occasion is still unexplained. Both
  known cases were a Deploy whose apply failed after its rollback, but the
  guards above now detect and mostly recover from it rather than leaving a dead
  login.

---

## 10. File inventory

| file | purpose |
|---|---|
| `resfile.py` / `origblob.py` | resolve `res:/` paths (current / pre-substitution) |
| `granny.py` / `grobj.py` / `gr2write.py` | Granny v7 reader, typed objects, writer |
| `oodle1.py` / `oodle1_cli.cpp` / `build.bat` | Oodle1 decompression |
| `black.py` | SOF `.black` container reader |
| `extract_venator_lod.py` / `build_venator_lod.py` | geometry pipeline |
| `bake_textures.py` / `composite_atlas.py` / `dds.py` | atlas UV, texture compositing, DDS output |
| `measure_mounts.py` / `measure_deck.py` | surface raycast, engine nozzle detection |
| `fit_ellipsoid.py` | enclosing-ellipsoid fit |
| `make_request.py` | assemble the authoring request from measurements |
| `author_venator.py` | native SOF hull authoring (runs in-client) |
| `render_icon.py` | ship icon rendering |
| `fsd_export.py` / `fsd_insert.py` / `fsd_deploy.py` | FSD table export, change sets, deploy |
| `loc_worker.py` / `make_loc_request.py` | localization messages |
| `server_patch.py` | EvEJS server ship / item / dogma rows |
| `install.py` | publish / revert resources |
| `finish_deploy.py` | the whole deploy in the correct order |
| `probe_hull.py` / `probe_template.py` / `verify_fsd.py` / `diff_hull.py` | verification |
| `py27c.cpp` / `py27shim.cpp` | Python 2.7 compiler and interpreter shim |
| `peek_pyj.py` / `decompile_pyj.py` | inspect client `.pyj` modules |
| `probe_lights.py` / `probe_faction.py` | SOF lighting sets, faction material slots |
| `measure_lights.py` / `fix_brightness.py` / `make_glow_map.py` | light anchors, texture levels, emissive atlas |
| `shipforge/server.py` | the editor's stdlib HTTP server and job runner |
| `shipforge/static/index.html` | the editor UI (three orthographic views) |
| `shipforge/pipeline.py` | build / preview / deploy / verify orchestration |
| `shipforge/blender_probe.py` | one-pass model probe: geometry, surface field, nozzles, anchors |
| `shipforge/blender_snap.py` | exact surface raycast for snapping |
| `shipforge/seed_venator.py` | seed a project from an existing build |

---

## 11. Rolling back

```bash
python fsd_deploy.py rollback     # client FSD tables
python install.py --revert        # resfileindex.txt
python server_patch.py revert     # server tables, then restart the container
```

Original blobs are never deleted — substitutions are written as *new* blobs under new
md5 names — so reverting is clean and complete. `code.ccp` is never modified.
