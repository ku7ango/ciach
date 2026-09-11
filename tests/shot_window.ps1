param([string]$Out, [int]$ProcId = 0)
# Zrzut okna przez PrintWindow (działa też dla okna zasłoniętego). Nie zabiera fokusu.
# -ProcId: PID procesu uruchomionego przez test (albo jego rodzica przy exe --onefile).
# Bez -ProcId bierze pierwsze okno "Ciach*", co może trafić w okno użytkownika: testy zawsze podają PID.
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class PW {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@
if ($ProcId -gt 0) {
  $ids = @($ProcId) + @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcId" | ForEach-Object { $_.ProcessId })
  $p = Get-Process | Where-Object { $ids -contains $_.Id -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
} else {
  $p = Get-Process | Where-Object { $_.MainWindowTitle -like "Ciach*" } | Select-Object -First 1
}
if (-not $p) { Write-Output "NO WINDOW"; exit 1 }
$h = $p.MainWindowHandle
$r = New-Object PW+RECT; [PW]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.R - $r.L; $hh = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $hh
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [PW]::PrintWindow($h, $hdc, 2)
$g.ReleaseHdc($hdc)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "saved $Out ($w x $hh) ok=$ok title=$($p.MainWindowTitle)"
