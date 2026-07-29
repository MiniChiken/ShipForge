# Putting a custom ship model into EVE Offline (EVE V24.01)

Getting a Star Wars Venator-class hull rendering in the EVE client running against
the local EvEJS server. This documents the working pipeline, the formats that had
to be reverse-engineered, and — just as importantly — the walls that stopped it.

**Status: the model rendered in-client**, at correct scale, with correct textures and
materials, by substituting the Armageddon's hull. A *genuinely new* ship (new typeID
with its own model, changing nothing else) turned out to be impossible — see
[What is blocked](#what-is-blocked).

---

## 0. What is and isn't in this repo

This is **tooling and documentation only**. Deliberately excluded:

* **The source model** — the Venator `.blend` and its textures are Lucasfilm/Disney
  IP from Sketchfab. Supply your own and point the scripts at it.
* **Decompiled EVE client Python** (`decomp/`, `inject/`) — CCP's code.
* **Extracted or derived game assets** — `.gr2`, `.dds`, `.black`, atlases. All are
  either CCP's content or reproducible by running the pipeline.
* **`liboodle`** — public domain (Unlicense), but a third-party repo. Clone it
  yourself: `git clone https://github.com/LunaticInAHat/liboodle ref`

Nothing here ships game content. The scripts read an EVE installation you already
have, and write into your own local client.

Everything below was worked out against **EVE V24.01 build 3396210** running on a
private, offline [EvEJS](https://github.com/rrfarmer/EveOffline) server. None of it
is intended for, or has been tested against, live Tranquility.

## 1. The short version

| | |
|---|---|
| Source model | `.blend` + 71 PBR PNGs (no exported mesh) |
| Client | EVE V24.01 build 3396210, `C:\EVE-EVEJS\client\EVE` |
| Result | 134,978-triangle Venator at 546 x 252 x 1137, on the Armageddon hull |
| Written from scratch | Granny `.gr2` reader **and writer**, Oodle1 decompressor, DDS writer, Python 2.7 patch toolchain |
| Hard blocker | `data.black` (SOF) — schema compiled into `_trinity_dx11.dll` |

---

## 2. How resources reach the client

The client reads `tq/resfileindex.txt` **once at process startup** and maps
`res:/...` paths to blobs in `ResFiles/`. Blobs are stored **uncompressed** on disk,
so publishing is: write the blob, rewrite the index line.

```
res:/path,<aa>/<pathhash>_<md5>,<md5>,<size>,<compressed_size>
```

`install.py` does this and keeps a backup:

```bash
python install.py --publish "res:/dx9/model/ship/.../ab2_t1.gr2"  venator.gr2
python install.py --revert            # restores the whole index
```

**Two things that cost real time:**

* **A relog is NOT enough.** The index is read at process start, and resources are
  cached in memory. Logging out to character select and back in serves the *old*
  build. You must kill and relaunch the client. Check with
  `Get-Process exefile | Select-Object Id,StartTime` — if `StartTime` predates the
  publish, you are not looking at your work.
* **New `res:` paths cannot be minted.** The `<pathhash>` is not md5/sha1/sha256/crc32
  of the path. Only paths already in the index can be republished.

---

## 3. The geometry pipeline

```
.blend ──Blender CLI──► venator_lod.{bin,json} ──build_venator_lod.py──► .gr2 ──install.py──► client
```

### 3.1 Extract (`extract_venator_lod.py`)

```bash
blender --background venator_atlas.blend --python extract_venator_lod.py -- <outdir>
```

Joins all objects, builds a LOD chain, and writes a flat vertex/index buffer.

**Axis transform — get this right first.** Blender `(x,y,z)` -> EVE `(x, z, -y)`.
That is a proper -90 deg rotation about X (determinant **+1**).

> The earlier `(x, z, y)` is a **reflection** (det -1) and produces three symptoms
> that look unrelated: the ship is **mirrored**, the **exhaust appears at the nose**,
> and **every triangle's winding inverts** (hull renders inside-out / invisible).
> With a proper rotation the source winding is already correct — do **not** also
> reverse indices, or you re-invert them.

Scale: **1 model unit ~= 1 metre**, measured across 8 stock battleships (ratio
0.85–1.11). `ArtToolInfo.UnitsPerMeter = 100` is vestigial Maya metadata, *not*
world scale. EVE battleships run 909–1529 units long; the Venator at 1137 sits
mid-range.

### 3.2 Build (`build_venator_lod.py`)

A hull must mirror the hull it replaces on **every** structural axis:

| field | requirement |
|---|---|
| vertex format | **per-hull** — read it from the target (see 4.2) |
| meshes | 7: `<Shape>` + its own LOD ladder (per-hull: `ab2_t1` uses 1280/640/320/160/80/10, `abc1_t1` uses 640…20) |
| `Materials` | **empty** — materials come from SOF, not the gr2 |
| `Skeletons` | 1 root bone named for the hull |
| `BoneBindings` | **1 per mesh**, bone name + OBB — without this the mesh is not attached to the skeleton and renders **invisible** |
| triangle groups | count == the hull's SOF opaque-area count, bound **by index** |
| root arrays | stock registers only **1** `VertexData`/`TriTopology` despite 7 meshes |

`diff_hull.py` compares a build against the stock hull field-by-field. **Use it before
every client test** — it found the missing bone bindings and the root-array mismatch
in one pass, after several restarts had been spent guessing one variable at a time.

Index width: stock uses 16-bit `Indices16` (65,535-vertex ceiling). The 32-bit
`Indices` array also works and lets the base LOD ship at full resolution instead of
being decimated to ~18%. Width is per-mesh, so LODs can mix.

---

## 4. Formats reverse-engineered

### 4.1 Granny `.gr2` container (`granny.py`, `gr2write.py`)

Two GUIDs are in use; the header behind both is identical Granny v7 64-bit LE.

```
0    magic[16]
16   headerSize u32 = 456
32   version u32 = 7 | totalSize | crc | sectionArrayOffset | sectionArrayCount = 8
104  section[8] x 44 bytes        <- ends exactly at headerSize
```

* `sectionArrayOffset` is relative to **offset 32**, not the file start.
* `DataTypeDefinition` is **packed 44 bytes** with *unaligned* pointers at +4 and +12
  (not the padded 48 you would expect).
* Relocations are 12 bytes: `{fromOffset, toSection, toOffset}`.
* `ReferenceToVariantArray` is **20 bytes** packed (`type*`, count, `obj*`).

**The key insight: Granny is self-describing.** Every file embeds its own type tree,
so a writer can mirror a real hull's schema instead of guessing — and the runtime
accepts `compression 0`, so **no compressor is needed**.

### 4.2 Oodle1 (`oodle1.py`, `oodle1_cli.cpp`)

Section compression 2 = Oodle1. Built from the public-domain
[`LunaticInAHat/liboodle`](https://github.com/LunaticInAHat/liboodle) C reference
(`build.bat`, VS 2022 BuildTools).

Framing: a section holds up to **three** streams. All three 12-byte headers sit at
payload offsets 0/12/24 and a **single shared bitstream** starts at offset 36 — the
streams cannot be sliced apart and decoded separately. Boundaries are
`{stop0, stop1, memSize}`.

*Known limitation:* faults with an access violation partway through very large
multi-stream sections (`gc4_t2a` sec0 decodes streams 0 and 1, dies on stream 2 at
5.8 MB). Small and single-stream sections are solid.

Compression **4 = BitKnit2** has no public reverse-engineering. Modern hulls use it
and simply cannot be read. Workaround: a hull's vertex format lives at **`sec6+0`**,
sec6 is small and usually decodes even when sec0 fails, and the format can be
recovered **structurally** (types + array widths) without sec0's name strings.

### 4.3 SOF `.black` (`black.py`) — container only

```
0  magic 0xb1acf11e | 4 version=1 | 8 dataOffset u32 (RELATIVE TO OFFSET 12) | 12 stringCount u16
14 .. 12+dataOffset   NUL-terminated string table
```

Verified byte-exact on `aliastra.black` (3.9 KB), `generic.black` (23 KB) and the full
`data.black` (180 MB) — parsed string count matches the header in all three.
`data.black` holds **502 SOF types**, 34,447 strings, 410 hull codes.

**The data region was not cracked.** See [What is blocked](#what-is-blocked).

### 4.4 Textures

Stock maps are 1024², 11 mips: `_a` BC7 sRGB, `_n` BC5/ATI2, and `_g/_m/_r/_p3/_d`
BC4/ATI1. **Uncompressed DDS works** — the client already ships 21 uncompressed
32bpp files, one at DX10 format 28. `dds.py` writes R8G8B8A8 + full mip chain; BC5
normals sample `.rg` and BC4 maps sample `.r`, so channel semantics still line up.
No BC encoder needed.

**Levels matter as much as content** (measured from stock `ab2_t1`):

| map | stock mean | meaning |
|---|---|---|
| `_a` | **198.7** | bright, near-white — EVE tints a light base via the material system |
| `_m` | 118.5 | selects among the faction's 4 material slots |
| `_p3` | ~0 | paint mask, effectively unused |
| `_r` | 219 | matte |

`_m` is a **brightness decision**: for `amarrbase` the slots are
`white_ivory_matt` / `grey_steel_brushed` / `black_gunmetal_metallic` /
`gold_true_polished`. Sending 9% of the hull to slot 3 produced black panels.

---

## 5. Building the texture atlas

The source model has 24 materials each with its own 0–1 UV space; an EVE hull area
samples **one** set of maps. So everything is packed into a 5x5 grid
(`bake_textures.py` builds the atlas UV and saves `venator_atlas.blend`).

**Do not Smart-UV-Project** — 134k polygons shatter into microscopic islands and the
atlas comes out nearly empty. Grid-pack each material's existing layout instead.

**Do not bake — composite** (`composite_atlas.py`). Cycles' NORMAL pass returned a
flat map (R/G std ~2/1 vs stock 20/30.6), losing all the model's normal-map detail,
and *a flat normal map is why the hull ignored scene lighting and went black when lit
head-on*. Since the atlas is just a grid of each material's original UV space, copy
each source texture straight into its cell: normal std 12.0, albedo std 33/44.

Other traps:
* A `DIFFUSE` bake returns **black for metallic materials** — bake Base Color through
  an Emission shader instead.
* `bpy.data.images ... save()` wrote all-zero PNGs; write `.npy` and convert with PIL
  outside Blender.
* Re-extract geometry from the **atlas** UV layer or the model and textures disagree.

---

## 6. What is blocked

### `data.black` — the wall

**The client ignores per-hull `hulls/*.black` files.** Proven by experiment: the
Armageddon's texture strings were repointed to slots holding obviously different maps,
geometry untouched — the ship rendered completely normal. Hull definitions come
**only** from the 180 MB monolith.

Its data region is schema-driven and the schema is **not in the file**. Established:

* not compressed (entropy 4.55 bits/byte, ~50% zero bytes)
* does **not** reference strings by table index (0 hits) **or** by byte offset (0 hits)
* contains almost no inline text (one UTF-16 string in 205 KB: `ship_engine_L_`)
* contains **no ship-scale float positions** — every float cluster is powers of two
  (+-512/128/32), i.e. shader parameters

Two candidate grammars were tested and **disproved**: u16 field/value pairs, and
ascending index runs. The pairing that looked convincing
(`material1 -> chrome_metallic`) is a coincidence — the raw values are just
9,10,11,12…, and only line up because that small file's string table happens to be in
document order. `ab2_t1`'s longest ascending run is 4 versus aliastra's 10.

Field names and order live compiled inside `_trinity_dx11.dll`.

**Consequently these cannot be changed:** booster/exhaust locators, hull lighting
(`EveSOFDataPointLightAttachment`), turret mount positions (`locatorTurrets`),
bounding sphere, and any new hull definition.

### Why a genuinely new ship is impossible

The client-Python route *works* — see section 7 — but the chain breaks at the end:

1. New typeID — **solved** (Python injection)
2. New graphicID — same technique
3. A graphicID must **name a hull**, and hull definitions come only from `data.black`
4. That definition **fixes the geometry and texture paths**
5. Exhaustive scan of all 2,538 hull definitions: **0** orphaned ship hulls have
   fully private, shipped assets. Every one either shares assets with a live ship
   (`mbc1_t2a` points at the Hurricane's `mbc1_t1.gr2`) or its assets were never
   shipped (`gf5_t1_redesign`'s `.gr2` is not in the index)
6. New `res:` paths cannot be minted (path hash not derivable)

So: **a new typeID, yes. A new ship that looks like the Venator without altering an
existing ship, no** — not without writing `data.black`.

---

## 7. Client Python patching (built, verified, unused)

`.pyj` = zlib'd Python 2.7 bytecode (magic 62211). No Python 2.7 on the machine and
none in winget — **but the client ships `tq/bin64/python27.dll`**, so it can compile
its own modules.

* `py27c.cpp` -> `py27c.exe` LoadLibrary's that DLL and runs
  `Py_Initialize` -> `Py_CompileString` -> `PyMarshal_WriteObjectToString` -> `.pyc`.
  Set `Py_NoSiteFlag` / `Py_NoUserSiteDirectory` / `Py_IgnoreEnvironmentFlag` first.
  The Stackless "tasklet cleanup" message at exit is harmless.
  A standalone host is required — loading `python27.dll` into a Python 3 process
  fails with *"Module use of python27.dll conflicts with this version of Python"*.
* `pip install uncompyle6` decompiles client modules. It chokes on
  `fsdBuiltData/common/base.pyj`; use `xdis.load_module` and walk `co_consts` instead.

**Injection point.** In `evetypes/__init__.py`, `GetTypes()` is literally
`Types.GetData()`, and `GetType` / `Exists` / `Iterate` / `GetAllTypeIDs` /
`GetAttributeForType` all funnel through it. `GetData` is a classmethod on
`BuiltDataLoader`. Wrapping it with a lazy merged mapping injects a typeID
everywhere; consumers need only `__getitem__`, `__contains__`, `iterkeys()`,
`keys()`. Working module: `inject/evetypes_data.py` (compiled and verified by
decompiling the output).

---

## 8. Stats and hardpoints

* **Stats — modifiable.** Server-side; `dogmaService.js` reads
  `readStaticTable(TABLE.TYPE_DOGMA)` from the game database. The Armageddon has 88
  attributes and 9 effects.
* **Fitting hardpoints — modifiable.** They are just dogma attributes:
  `hiSlots` 14, `medSlots` 13, `lowSlots` 12, `turretSlotsLeft` 102,
  `launcherSlotsLeft` 101, **`fighterTubes` 2216**, **`fighterCapacity` 2055`.
* **Turret mount positions — blocked.** `locatorTurrets` lives in `data.black`.

Caveat: the client keeps its own `typedogma.fsdbinary`, and the fitting window reads
from that, so server-only changes can desync the displayed numbers. The Python
toolchain in section 7 could inject client-side values to match.

---

## 9. File inventory

| file | purpose |
|---|---|
| `resfile.py` / `origblob.py` | resolve `res:/` paths (current / pre-substitution) |
| `granny.py` / `grobj.py` | Granny v7 container + typed object reader |
| `gr2write.py` | Granny writer (uncompressed) |
| `oodle1.py` / `oodle1_cli.cpp` / `build.bat` | Oodle1 decompression |
| `black.py` / `black_edit.py` | `.black` container reader / string-table rewriter |
| `bake_textures.py` / `composite_atlas.py` | atlas UV + texture compositing |
| `dds.py` / `fix_levels.py` / `make_material_map.py` | DDS output and level matching |
| `extract_venator_lod.py` / `build_venator_lod.py` | geometry pipeline |
| `diff_hull.py` / `check_winding.py` / `hullinfo.py` | validation |
| `py27c.cpp` / `inject/` | client Python patch toolchain |
| `install.py` | publish / revert |

---

## 10. Rolling back

```bash
python install.py --revert
```

Restores `tq/resfileindex.txt` from `resfileindex.txt.venator-backup`. Original blobs
are never deleted — substitutions are written as *new* blobs under new md5 names — so
reverting is clean and complete. `code.ccp` was never modified.
