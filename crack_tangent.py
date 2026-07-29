"""Brute-force how EVE packs the normal into the 4-byte Tangent field.

Symptom that forced this: the hull does not respond to scene lighting and goes
near-black when the light is behind the camera - i.e. wrong normals. The vertex
format carries NO normal, so the shader must rebuild it from these 4 bytes.

Earlier tests assumed byte order (x,y,z,w) and the mapping v/255*2-1. This
searches component subsets, permutations, sign flips and two scalings, scoring
each against per-vertex normals computed from the mesh itself.
"""
import itertools
import struct

import numpy as np

import check_tangent as C
import granny


def geometric_normals(pos, tris):
    acc = np.zeros_like(pos)
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)
    for k in range(3):
        np.add.at(acc, tris[:, k], fn)
    ln = np.linalg.norm(acc, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return acc / ln


def score(v, n):
    ln = np.linalg.norm(v, axis=1, keepdims=True)
    ln[ln == 0] = 1
    v = v / ln
    d = (v * n).sum(axis=1)
    d = d[np.isfinite(d)]
    return np.abs(d).mean(), (np.abs(d) > 0.9).mean()


def crack(path_bytes, label):
    gf = granny.GrannyFile(path_bytes)
    pos, tan, uv, tris = C.load(gf)
    n = geometric_normals(pos, tris)
    t = tan.astype(np.float64)

    scalings = {
        "v/255*2-1": lambda a: a / 255.0 * 2 - 1,
        "(v-128)/127": lambda a: (a - 128.0) / 127.0,
    }
    results = []
    for sname, fn in scalings.items():
        s = fn(t)
        for trio in itertools.permutations(range(4), 3):
            for signs in itertools.product((1, -1), repeat=3):
                v = np.stack([s[:, trio[0]] * signs[0],
                              s[:, trio[1]] * signs[1],
                              s[:, trio[2]] * signs[2]], axis=1)
                m, hi = score(v, n)
                results.append((m, hi, sname, trio, signs))
    results.sort(reverse=True)
    print("== %s ==" % label)
    print("  %-14s %-12s %-14s %8s %8s" % ("scaling", "bytes", "signs", "mean|dot|", ">0.9"))
    for m, hi, sname, trio, signs in results[:6]:
        print("  %-14s %-12s %-14s %8.3f %7.1f%%"
              % (sname, str(trio), str(signs), m, 100 * hi))
    return results[0]
