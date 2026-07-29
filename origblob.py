"""Resolve a res:/ path against the PRE-substitution index backup.

Once install.py rewrites an index line, resfile.py returns the substituted file.
This reads the original blob so a hull can still be studied after publishing
over it.
"""
import os

CLIENT = r"C:\EVE-EVEJS\client\EVE"
BACKUP = os.path.join(CLIENT, "tq", "resfileindex.txt.venator-backup")
RESFILES = os.path.join(CLIENT, "ResFiles")


def path(res_path):
    target = res_path.lower()
    with open(BACKUP, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split(",")
            if parts and parts[0].lower() == target:
                return os.path.join(RESFILES, parts[1].replace("/", os.sep))
    raise KeyError(res_path)


def read(res_path):
    with open(path(res_path), "rb") as fh:
        return fh.read()
