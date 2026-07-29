# Capture ONE window by HWND - never the desktop.
# The desktop shows live home-camera feeds, so full-screen capture is off limits.
# PrintWindow copies only the target window's own client area.
#
# grabwindow.ps1 targets a process's MainWindowHandle, which is no use when the
# process owns several top-level windows (the Trinity viewer's main window is its
# floating control panel, not the render surface), so this takes the handle.
param(
    [Parameter(Mandatory = $true)][long]$Hwnd,
    [Parameter(Mandatory = $true)][string]$Out
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinCapH {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$h = [IntPtr]::new($Hwnd)
if ([WinCapH]::IsIconic($h)) { [WinCapH]::ShowWindow($h, 9) | Out-Null; Start-Sleep -Milliseconds 600 }
[WinCapH]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 900

$r = New-Object WinCapH+RECT
[WinCapH]::GetClientRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left
$ht = $r.Bottom - $r.Top
if ($w -le 0 -or $ht -le 0) { Write-Error "bad window size ${w}x${ht}"; exit 1 }

Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
# nFlags=2 (PW_RENDERFULLCONTENT) is required for GPU-composited windows
$ok = [WinCapH]::PrintWindow($h, $hdc, 2)
$g.ReleaseHdc($hdc)
$g.Dispose()
if (-not $ok) { Write-Error "PrintWindow failed for hwnd $Hwnd"; exit 1 }
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
"saved $Out (${w}x${ht})"
