# Lance le run quotidien ATLAS puis rendort le PC s'il etait inactif.
# Appele par la tache planifiee "ATLAS Daily Run" (qui reveille le PC a 23h).
#
# Logique:
#  1. Empeche la mise en veille PENDANT le run (sinon le PC, reveille par le
#     minuteur sans activite utilisateur, se rendormirait au bout de qq min).
#  2. Lance le scan + paper + sentiment + notification Telegram.
#  3. Si l'utilisateur n'a rien touche depuis >= 5 min (donc PC reveille par le
#     minuteur, personne devant), rendort le PC. Sinon, laisse allume pour ne
#     pas couper une session active.

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Power {
  [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);
  [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);
  public static uint GetIdleSeconds() {
    LASTINPUTINFO lii = new LASTINPUTINFO();
    lii.cbSize = (uint)Marshal.SizeOf(lii);
    GetLastInputInfo(ref lii);
    return ((uint)Environment.TickCount - lii.dwTime) / 1000;
  }
}
'@

# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001): garde le PC eveille
[void][Power]::SetThreadExecutionState([uint32]"0x80000001")

Set-Location "C:\bot trading\atlas"
& ".\.venv\Scripts\python.exe" -m atlas.pipelines.daily_run

# Mesure l'inactivite AVANT de relacher le maintien eveille
$idle = [Power]::GetIdleSeconds()

# Relache le maintien eveille (ES_CONTINUOUS seul)
[void][Power]::SetThreadExecutionState([uint32]"0x80000000")

if ($idle -ge 300) {
    # Personne devant le PC: on le rendort (Suspend = veille, pas hibernation)
    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)
}
