"""Detach the custom ship from the SAVE so the client can go vanilla.

go_vanilla() returns the client and server to stock, but it refuses to run while
a character still OWNS the custom ship: going vanilla strips typeID 900001 from
the client's tables, and an item referencing a type the client cannot resolve
kills it at character select. That guard is right, and forcing past it is the
failure we already hit twice.

Clearing the way is not a single DELETE, because the ship is entangled:

  * 23 modules sit INSIDE it - a full deadspace fit (Gotan's, Estamel's,
    Cormack's). Deleting the hull would orphan every one of them, so they are
    moved to the owner's station hangar first, with their original
    locationID/flagID recorded so a restore can re-fit them.
  * the character is IN SPACE in it (stationID null, shipID = the hull), so it
    also has to be docked and re-seated in another ship it owns, or it wakes up
    piloting nothing.
  * moduleGroupingState carries a "ships<itemID>" row.
  * _persistence_outbox holds a PENDING upsert of the hull. Left alone, the
    server would re-apply it and resurrect the ship after the rollback.

Everything removed or changed is written to a manifest beside a full copy of
gamestore.sqlite, so --restore puts the save back exactly as it was.

    python park_venator.py --dry-run
    python park_venator.py            # park: detach, then it is safe to go vanilla
    python park_venator.py --restore <manifest.json>
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESTORE = HERE / "restore"
CONTAINER = "evejs-fresh-server-1"
DB_IN_CONTAINER = "/var/lib/evejs/gameStore/gamestore.sqlite"
HANGAR_FLAG = 4


def project():
    return json.loads((HERE / "shipforge" / "projects" / "venator.json")
                      .read_text("utf-8"))


def run(*args, **kw):
    print("$ " + " ".join(str(a) for a in args))
    result = subprocess.run(args, capture_output=True, text=True, **kw)
    if result.returncode:
        raise SystemExit("FAILED: %s\n%s" % (" ".join(map(str, args)),
                                             result.stderr.strip()))
    return result.stdout.strip()


def pull(local):
    run("docker", "cp", "%s:%s" % (CONTAINER, DB_IN_CONTAINER), str(local))


def push(local):
    run("docker", "cp", str(local), "%s:%s" % (CONTAINER, DB_IN_CONTAINER))


def rows(connection, table):
    return list(connection.execute('select key, json from "%s"' % table))


def park(dry_run):
    type_id = int(project().get("typeID", 900001))
    RESTORE.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = RESTORE / ("gamestore-%s.sqlite" % stamp)
    pull(work)
    print("pulled %s (%d bytes)" % (work.name, work.stat().st_size))

    connection = sqlite3.connect(str(work))
    connection.row_factory = None
    try:
        hulls = [(k, json.loads(b)) for k, b in rows(connection, "items")
                 if json.loads(b).get("typeID") == type_id]
        if not hulls:
            print("no item references typeID %d - nothing to park" % type_id)
            return
        manifest = {"parkedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "typeID": type_id, "gamestoreBackup": work.name,
                    "hulls": [], "contents": [], "characters": [],
                    "moduleGrouping": [], "outbox": []}

        for key, hull in hulls:
            owner = hull.get("ownerID")
            item_id = hull.get("itemID")
            print("\nhull %s (%s) owned by %s" % (item_id, hull.get("itemName"), owner))
            manifest["hulls"].append({"key": key, "json": hull})

            # where the owner's other ships live - that is a real hangar
            hangar = None
            for other_key, blob in rows(connection, "items"):
                other = json.loads(blob)
                if (other.get("ownerID") == owner and other.get("categoryID") == 6
                        and other.get("itemID") != item_id
                        and other.get("flagID") == HANGAR_FLAG):
                    hangar = other
                    break
            if hangar is None:
                raise SystemExit("owner %s has no other hangared ship to move "
                                 "the fit into, or to re-seat into" % owner)
            station = hangar.get("locationID")
            print("  target hangar: station %s (via %s %s)"
                  % (station, hangar.get("itemName"), hangar.get("itemID")))

            # 1. rescue everything inside the hull
            moved = 0
            for other_key, blob in rows(connection, "items"):
                inner = json.loads(blob)
                if inner.get("locationID") != item_id:
                    continue
                manifest["contents"].append(
                    {"key": other_key, "locationID": inner.get("locationID"),
                     "flagID": inner.get("flagID")})
                inner["locationID"] = station
                inner["flagID"] = HANGAR_FLAG
                if not dry_run:
                    connection.execute(
                        "update items set json = ? where key = ?",
                        (json.dumps(inner), other_key))
                moved += 1
            print("  moved %d contained items to the station hangar" % moved)

            # 2. re-seat any character flying it
            for char_key, blob in rows(connection, "characters"):
                character = json.loads(blob)
                if character.get("shipID") != item_id:
                    continue
                manifest["characters"].append(
                    {"key": char_key,
                     "before": {k: character.get(k) for k in
                                ("shipID", "shipName", "shipTypeID",
                                 "stationID", "solarSystemID")}})
                character["shipID"] = hangar.get("itemID")
                character["shipName"] = hangar.get("itemName")
                character["shipTypeID"] = hangar.get("typeID")
                character["stationID"] = station
                if not dry_run:
                    connection.execute(
                        "update characters set json = ? where key = ?",
                        (json.dumps(character), char_key))
                print("  re-seated character %s into %s and docked at %s"
                      % (char_key, hangar.get("itemName"), station))

            # 3. per-ship UI state. The key is "ships<0x1f><itemID>" - a UNIT
            # SEPARATOR, not a plain join, and it prints as if it were not there,
            # so an obvious "ships%s" never matched and the row survived silently.
            # Compare the trailing field instead of guessing the separator.
            for k, blob in rows(connection, "moduleGroupingState"):
                if k.split("\x1f")[-1] != str(item_id):
                    continue
                manifest["moduleGrouping"].append({"key": k, "json": blob})
                if not dry_run:
                    connection.execute(
                        "delete from moduleGroupingState where key = ?", (k,))
                print("  removed moduleGroupingState %s" % k)

            # 4. the hull itself
            if not dry_run:
                connection.execute("delete from items where key = ?", (key,))
            print("  removed the hull item")

        # 5. pending writes that would put it straight back
        pending = list(connection.execute(
            "select operation_id, table_name, upserts_json, deletes_json, state"
            " from _persistence_outbox"))
        for op_id, table, upserts, deletes, state in pending:
            if str(type_id) not in ((upserts or "") + (deletes or "")):
                continue
            manifest["outbox"].append(
                {"operation_id": op_id, "table_name": table,
                 "upserts_json": upserts, "deletes_json": deletes,
                 "state": state})
            if not dry_run:
                connection.execute(
                    "delete from _persistence_outbox where operation_id = ?",
                    (op_id,))
            print("\nremoved pending outbox op %s on %s (state %s) - it would "
                  "have re-created the hull" % (op_id, table, state))

        if dry_run:
            connection.rollback()
            print("\ndry run - nothing written, no container touched")
            return
        connection.commit()
    finally:
        connection.close()

    path = RESTORE / ("park-%s.json" % stamp)
    path.write_text(json.dumps(manifest, indent=1), "utf-8")
    print("\nwrote %s" % path)

    print("\nstopping the server so the database is not in use")
    run("docker", "stop", CONTAINER)
    push(work)
    run("docker", "start", CONTAINER)
    print("\nPARKED. go_vanilla will now pass its ownership gate.")
    print("Restore with: python park_venator.py --restore %s" % path.name)


def restore(name):
    path = RESTORE / name if not os.path.isabs(name) else Path(name)
    manifest = json.loads(Path(path).read_text("utf-8"))
    backup = RESTORE / manifest["gamestoreBackup"]
    if not backup.is_file():
        raise SystemExit("missing %s - cannot restore" % backup)
    print("restoring the whole gamestore from %s" % backup.name)
    print("this reverts EVERY change made since it was taken, not just the ship")
    run("docker", "stop", CONTAINER)
    push(backup)
    run("docker", "start", CONTAINER)
    print("RESTORED. Re-enable the ship with ShipForge Deploy.")


if __name__ == "__main__":
    if "--restore" in sys.argv:
        restore(sys.argv[sys.argv.index("--restore") + 1])
    else:
        park("--dry-run" in sys.argv)
