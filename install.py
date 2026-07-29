"""Publish a file into the EVE client's resource cache, reversibly.

Adding a resource means writing a blob into ResFiles/ and pointing a line in
tq/resfileindex.txt at it. Index lines look like:

    res:/path,<aa>/<pathhash>_<md5>,<md5>,<size>,<compressed_size>

The <pathhash> is derived from the res: path, so republishing an existing path
reuses its prefix and only the md5/sizes change. Blobs are stored uncompressed,
so compressed_size is just the size.

The original index is backed up on first run; --revert restores it.

    python install.py --publish <res:/path> <local file>
    python install.py --revert
"""
import hashlib
import os
import shutil
import sys

CLIENT = r"C:\EVE-EVEJS\client\EVE"
INDEX = os.path.join(CLIENT, "tq", "resfileindex.txt")
BACKUP = INDEX + ".venator-backup"
RESFILES = os.path.join(CLIENT, "ResFiles")


def load_lines():
    with open(INDEX, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read().splitlines()


def backup_once():
    if not os.path.exists(BACKUP):
        shutil.copy2(INDEX, BACKUP)
        print("backed up index -> %s" % BACKUP)
    else:
        print("backup already exists (%s), left untouched" % BACKUP)


def revert():
    if not os.path.exists(BACKUP):
        print("no backup found; nothing to revert")
        return 1
    shutil.copy2(BACKUP, INDEX)
    print("restored %s from backup" % INDEX)
    return 0


def publish(res_path, local):
    backup_once()
    data = open(local, "rb").read()
    md5 = hashlib.md5(data).hexdigest()
    lines = load_lines()

    target = res_path.lower()
    idx = None
    prefix = None
    for i, line in enumerate(lines):
        parts = line.split(",")
        if parts and parts[0].lower() == target:
            idx = i
            prefix = parts[1].split("_")[0]   # "<aa>/<pathhash>"
            break
    if prefix is None:
        # Brand-new logical path. The physical prefix is OPAQUE - the client does
        # not recompute or verify it, it just follows the index mapping. So any
        # deterministic allocator works; sha256 of the lowercased logical path is
        # the convention used by the Elysian kit.
        h = hashlib.sha256(res_path.lower().encode("utf-8")).hexdigest()[:16]
        prefix = "%s/%s" % (h[:2], h)
        lines.append("")          # placeholder row, filled in below
        idx = len(lines) - 1
        print("minted new logical path %s -> %s" % (res_path, prefix))

    blob_rel = "%s_%s" % (prefix, md5)
    blob_abs = os.path.join(RESFILES, blob_rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(blob_abs), exist_ok=True)
    with open(blob_abs, "wb") as fh:
        fh.write(data)

    lines[idx] = "%s,%s,%s,%d,%d" % (res_path, blob_rel, md5, len(data), len(data))
    with open(INDEX, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print("published %s" % res_path)
    print("   blob  %s (%d bytes)" % (blob_rel, len(data)))
    print("   index line %d rewritten" % (idx + 1))
    return 0


if __name__ == "__main__":
    if "--revert" in sys.argv:
        sys.exit(revert())
    if "--publish" in sys.argv:
        i = sys.argv.index("--publish")
        sys.exit(publish(sys.argv[i + 1], sys.argv[i + 2]))
    print(__doc__)
