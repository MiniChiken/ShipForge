"""Resolve res:/ paths to their on-disk blobs in the EVE ResFiles cache.

The client reads tq/resfileindex.txt, whose lines are:
    res:/path,<aa>/<hash>_<md5>,<md5>,<size>,<compressed_size>[,<mode>]
Blobs are stored uncompressed on disk, so resolving is just a path join.
"""
import os

CLIENT = r"C:\EVE-EVEJS\client\EVE"
INDEX = os.path.join(CLIENT, "tq", "resfileindex.txt")
RESFILES = os.path.join(CLIENT, "ResFiles")

_index = None


def load_index(path=INDEX):
    """Return {res_path_lower: (blob_rel, md5, size, comp_size)}."""
    global _index
    if _index is not None:
        return _index
    out = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split(",")
            if len(parts) < 5:
                continue
            res, blob, md5, size, comp = parts[0], parts[1], parts[2], parts[3], parts[4]
            try:
                out[res.lower()] = (blob, md5, int(size), int(comp))
            except ValueError:
                continue
    _index = out
    return out


def blob_path(res_path):
    """Absolute path to the cached blob backing a res:/ path."""
    entry = load_index().get(res_path.lower())
    if entry is None:
        raise KeyError(res_path)
    return os.path.join(RESFILES, entry[0].replace("/", os.sep))


def read(res_path):
    with open(blob_path(res_path), "rb") as fh:
        return fh.read()


def find(substr, limit=None):
    """res:/ paths containing substr (case-insensitive)."""
    s = substr.lower()
    hits = [p for p in load_index() if s in p]
    hits.sort()
    return hits[:limit] if limit else hits
