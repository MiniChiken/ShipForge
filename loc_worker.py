from __future__ import print_function

# Python 2.7 worker, run inside the EVE client:
#     exefile.exe /py loc_worker.py <result.json> <request.json> /inherit
#
# Appends a message ID to every shipped localization_fsd_<lang>.pickle.
#
# These are read through the client's whitelistpickle. Re-pickling in Python 3
# emits _codecs.encode globals and the client dies at startup with
#     UnpicklingError: _codecs.encode not in whitelist
# so this deliberately runs under the client's own 2.7 and writes protocol 0.

import json
import os
import sys
import traceback

import cPickle


def read_json(path):
    h = open(path, "rb")
    try:
        return json.loads(h.read())
    finally:
        h.close()


def write_json(path, value):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    h = open(path, "wb")
    try:
        h.write(json.dumps(value, indent=2, sort_keys=True))
    finally:
        h.close()


def describe(obj, depth=0):
    """Small structural summary so we can confirm the row shape before writing."""
    if isinstance(obj, dict):
        keys = list(obj.keys())[:3]
        sample = obj[keys[0]] if keys else None
        return {"type": "dict", "len": len(obj),
                "sampleKeys": [repr(k) for k in keys],
                "sampleValue": repr(sample)[:200]}
    if isinstance(obj, (list, tuple)):
        return {"type": type(obj).__name__, "len": len(obj),
                "sample": repr(obj[:2])[:200]}
    return {"type": type(obj).__name__, "repr": repr(obj)[:200]}


def main():
    result_path = sys.argv[1]
    request_path = sys.argv[2]
    result = {"success": False, "files": []}
    try:
        import blue
        req = read_json(request_path)
        # Accept either a single messageID/text or a list, so the ship name and
        # its description go in together - each pass over these pickles rewrites
        # ~200MB, and a second pass would have to re-read what the first wrote.
        if "messages" in req:
            messages = [(int(m["messageID"]), m["text"]) for m in req["messages"]]
        else:
            messages = [(int(req["messageID"]), req["text"])]
        inspect_only = bool(req.get("inspectOnly"))

        for entry in req["files"]:
            logical = entry["logical"]
            source = entry["source"]
            output = entry["output"]

            handle = open(source, "rb")
            try:
                data = cPickle.load(handle)
            finally:
                handle.close()

            info = {"logical": logical, "structure": describe(data)}

            # Shipped shape is a 2-tuple: (langCode, {messageID: (text, None, None)})
            container = None
            if isinstance(data, dict):
                container = data
            elif isinstance(data, (tuple, list)):
                for element in data:
                    if isinstance(element, dict):
                        container = element
                        break
            if container is None:
                info["error"] = "no dict container in root"
                result["files"].append(info)
                continue

            info["hasMessage"] = [mid in container for mid, _ in messages]
            info["messageCount"] = len(container)
            try:
                info["maxMessageID"] = max(
                    k for k in container.keys() if isinstance(k, (int, long)))
            except ValueError:
                info["maxMessageID"] = None
            if not inspect_only:
                existing = None
                for value in container.values():
                    existing = value
                    break
                wrote = []
                for message_id, text in messages:
                    # match the shipped row shape exactly, e.g. (text, None, None)
                    if isinstance(existing, tuple):
                        row = tuple([text] + [None] * (len(existing) - 1))
                    elif isinstance(existing, list):
                        row = [text] + [None] * (len(existing) - 1)
                    else:
                        row = text
                    container[message_id] = row
                    wrote.append("%d=%s" % (message_id, repr(row)[:80]))
                info["wroteRow"] = wrote
                parent = os.path.dirname(output)
                if parent and not os.path.isdir(parent):
                    os.makedirs(parent)
                # Preserve the shipped protocol. The whitelist hazard is a
                # PYTHON 3 repickle emitting _codecs.encode globals; pickling
                # Python 2 objects from Python 2 never does. Forcing protocol 0
                # here would also inflate these files enormously (ru is 148 MB).
                probe = open(source, "rb")
                try:
                    head = probe.read(2)
                finally:
                    probe.close()
                protocol = 2 if head[:1] == b"\x80" else 0
                info["protocol"] = protocol
                out = open(output, "wb")
                try:
                    cPickle.dump(data, out, protocol)
                finally:
                    out.close()
                info["output"] = output
                info["outputSize"] = os.path.getsize(output)
                info["count"] = len(container)
            result["files"].append(info)
        result["success"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    write_json(result_path, result)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
