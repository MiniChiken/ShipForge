"""Launch the Trinity viewer at a chosen framing, drive it, and capture it.

Turret and booster placement has to be judged against the game's own renderer,
and the viewer is interactive - so this uses the two scripted channels it
exposes rather than a mouse:

  * RADIUS on the command line sets camera distance, so a small value frames
    close (there is no zoom command)
  * the COMMAND_JSONL file is polled ~12x/sec for {"command": ...} lines

Capture is per-WINDOW by HWND, never the desktop. The viewer owns two top-level
windows and its MainWindowHandle is the floating control panel, not the render
surface, so the render window is picked out by title.

    python viewshot.py <out.png> [radius] [yaw] [pitch] [roll]
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
BASE = "http://127.0.0.1:8770"
COMMANDS = Path(r"C:\evejs\tools\trinity-viewer\runtime\commands")

FIND_RENDER_WINDOW = r"""
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
using System.Collections.Generic;
public class VW {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public static List<string> All(){
    var o = new List<string>();
    EnumWindows((h,p)=>{
      if(IsWindowVisible(h)){
        var sb=new StringBuilder(400); GetWindowText(h,sb,400);
        var t=sb.ToString();
        if(t.StartsWith("Elysian Jessica Live")) o.Add(h.ToInt64()+"|"+t);
      }
      return true;
    }, IntPtr.Zero);
    return o;
  }
}
'@
[VW]::All() | ForEach-Object { $_ }
"""


def post(path, body):
    request = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request).read())


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path).read())


def powershell(script):
    return subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True).stdout.strip()


def find_render_window():
    for line in powershell(FIND_RENDER_WINDOW).splitlines():
        if "|" in line:
            handle, title = line.split("|", 1)
            return int(handle), title
    return None, None


def main():
    out = sys.argv[1]
    radius = float(sys.argv[2]) if len(sys.argv) > 2 else 140.0
    yaw = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    pitch = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    roll = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0

    # close any viewer already up, so the window we find is the one we launched
    powershell("Get-Process exefile -ErrorAction SilentlyContinue | "
               "Where-Object { $_.MainWindowTitle -like 'Jessica*' } | "
               "Stop-Process -Force")
    time.sleep(2)

    project = get("/api/project/venator")
    project = json.loads(json.dumps(project))
    project.setdefault("shield", {})["sphere"] = radius     # camera framing only
    job = post("/api/preview", {"project": project, "width": 1400, "height": 900})
    for _ in range(60):
        time.sleep(2)
        state = get("/api/job/" + job["job"])
        if state["state"] != "running":
            break
    if state["state"] != "done":
        print("preview failed:", state.get("error"))
        return 1

    handle = None
    for _ in range(40):
        time.sleep(2)
        handle, title = find_render_window()
        if handle:
            print("render window %d: %s" % (handle, title[:110]))
            break
    if not handle:
        print("render window never appeared")
        return 1

    command_file = COMMANDS / "shipforge-venator_t1.jsonl"
    with command_file.open("a") as fh:
        for line in ({"command": "arm"},
                     {"command": "boosters", "value": True},
                     {"command": "modelorientation",
                      "yaw": yaw, "pitch": pitch, "roll": roll}):
            fh.write(json.dumps(line) + "\n")
    print("sent arm + boosters + orientation yaw=%s pitch=%s roll=%s"
          % (yaw, pitch, roll))
    time.sleep(9)          # let turrets mount and the orientation settle

    print(powershell(
        "& '%s' -Hwnd %d -Out '%s'"
        % (TOOLS / "grabhwnd.ps1", handle, out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
