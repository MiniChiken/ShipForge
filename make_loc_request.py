"""Rewrite loc_request.json to carry both the ship name and its description.

The `files` list (logical path -> pristine ResFiles blob -> output) is preserved
from the existing request; only the message payload changes. Sources are the
PRE-substitution blobs, so each run rebuilds every pickle from shipped state
plus our messages rather than layering onto a previously patched copy.

Description is written from the Wookieepedia Venator-class article, in our own
words. Pure ASCII: these pickles are read back through the client's
whitelistpickle and there is no reason to risk an encoding on top of that.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

NAME_MESSAGE_ID = 9000001
DESC_MESSAGE_ID = 9000002

NAME = "Venator"

DESCRIPTION = (
    "A 1,137 metre attack cruiser of the Star Destroyer line, designed by Lira "
    "Wessex and built by Kuat Drive Yards for the Republic Navy. Its double-wedge "
    "hull was drawn up for a wide range of duties: it fights as a capital line "
    "combatant, but a broad forward flight deck and three further docking bays "
    "let it serve equally as a starfighter carrier, troop transport and fleet "
    "supply vessel. Heavy deflector shields and layered armour plating cover its "
    "batteries of turbolasers and point defence cannons. Widely flown as a "
    "flagship by the Jedi Generals of the Grand Army, it became the backbone of "
    "the Republic fleet and passed afterwards into Imperial service."
)


def main():
    path = HERE / "loc_request.json"
    request = json.loads(path.read_text("utf-8"))
    request.pop("messageID", None)
    request.pop("text", None)
    request["inspectOnly"] = False
    request["messages"] = [
        {"messageID": NAME_MESSAGE_ID, "text": NAME},
        {"messageID": DESC_MESSAGE_ID, "text": DESCRIPTION},
    ]
    path.write_text(json.dumps(request, indent=1), "utf-8")
    assert DESCRIPTION.isascii(), "description must stay ASCII"
    print("wrote %s" % path)
    print("  %d files, %d messages" % (len(request["files"]), len(request["messages"])))
    print("  %d = %s" % (NAME_MESSAGE_ID, NAME))
    print("  %d = %d chars" % (DESC_MESSAGE_ID, len(DESCRIPTION)))


if __name__ == "__main__":
    main()
