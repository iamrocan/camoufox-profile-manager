<#
    Why the manager will not start on this machine.

    Prints one labelled report covering every cause we have actually hit, in the
    order it is worth ruling them out. Nothing here changes the machine: the
    only thing it starts is the server on a spare port, which it then stops.

    Usage, from anywhere:

        powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1
        powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 -Dir D:\camoufox

    Paste the whole output when reporting a launch failure. Section 7 separates
    the two failures that look identical from outside -- a server that will not
    boot from a window that will not open -- and that is usually the answer.
#>
param([string]$Dir = $(Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'SilentlyContinue'
$py = Join-Path $Dir '.venv\Scripts\python.exe'

"=== 1 CARPETA ==="
"ruta   : " + $Dir
"existe : " + (Test-Path $Dir)

"=== 2 COMMIT ==="
(& git -C $Dir log --oneline -1 2>&1 | Out-String).Trim()

"=== 3 ARCHIVOS ==="
foreach ($f in 'launch.vbs', 'launch.bat', 'install.py', '.venv\Scripts\python.exe', '.venv\Scripts\pythonw.exe') {
    "{0,-32} {1}" -f $f, (Test-Path (Join-Path $Dir $f))
}

# Smart App Control blocks the unsigned console scripts; see CLAUDE.md. Nothing
# in this repository calls them any more, so a 1 here is only the answer if
# section 5 also shows the interpreter itself unsigned.
"=== 4 SMART APP CONTROL (0 apagado, 1 bloqueando, 2 evaluando) ==="
"estado : " + (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy').VerifiedAndReputablePolicyState

"=== 5 FIRMAS DEL VENV ==="
foreach ($f in 'python.exe', 'pythonw.exe', 'camoufox-pm.exe') {
    $p = Join-Path $Dir ('.venv\Scripts\' + $f)
    if (Test-Path $p) {
        $s = Get-AuthenticodeSignature $p
        "{0,-16} {1,-12} {2}" -f $f, $s.Status, $(if ($s.SignerCertificate) { $s.SignerCertificate.Subject.Split(',')[0] } else { '-' })
    }
}

# A venv built on a Python that uv downloaded itself is not PSF-signed, which
# would put the interpreter in the same boat as the stubs under SAC.
"=== 6 PYTHON BASE DEL VENV ==="
(Get-Content (Join-Path $Dir '.venv\pyvenv.cfg') | Out-String).Trim()

"=== 7 IMPORTA EL PAQUETE Y PYWEBVIEW? ==="
(& $py -c "import sys; print(sys.version); import camoufox_pm; print('camoufox_pm OK'); import webview; print('pywebview OK')" 2>&1 | Out-String).Trim()

"=== 8 RESPONDE EL CLI? ==="
(& $py -m camoufox_pm.cli --help 2>&1 | Select-Object -First 2 | Out-String).Trim()

# pywebview renders in WebView2 on Windows. Without the runtime the server
# starts fine and only the window fails, which from outside looks identical to
# the app not starting at all.
"=== 9 WEBVIEW2 RUNTIME (lo necesita --desktop) ==="
$guid = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
$v = (Get-ItemProperty ('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + $guid)).pv
if (-not $v) { $v = (Get-ItemProperty ('HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\' + $guid)).pv }
if ($v) { "instalado, version " + $v } else { "NO INSTALADO  <-- la ventana propia no puede abrir sin esto" }

"=== 10 ARRANCA EL SERVIDOR (puerto 8899, sin ventana)? ==="
$out = Join-Path $env:TEMP 'cpm_diag_out.log'
$err = Join-Path $env:TEMP 'cpm_diag_err.log'
$proc = Start-Process -FilePath $py -ArgumentList '-m', 'camoufox_pm.cli', '--port', '8899', '--no-browser' `
    -WorkingDirectory $Dir -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
Start-Sleep -Seconds 8
$r = Invoke-WebRequest -Uri 'http://127.0.0.1:8899/' -UseBasicParsing -TimeoutSec 5
if ($r.StatusCode) {
    "SI - responde HTTP " + $r.StatusCode
} else {
    "NO responde. Ultimas lineas del error:"
    (Get-Content $err -Tail 12 | Out-String).Trim()
}
if ($proc) { Stop-Process -Id $proc.Id -Force }

# A stale process still holding the port makes a fresh launch look like a
# shortcut that does nothing at all.
"=== 11 PUERTO 8000 ==="
$c = Get-NetTCPConnection -LocalPort 8000 -State Listen
if ($c) { foreach ($x in $c) { "ocupado por PID " + $x.OwningProcess + " (" + (Get-Process -Id $x.OwningProcess).ProcessName + ")" } } else { "libre" }

"=== 12 BLOQUEOS CODEINTEGRITY (7 dias) ==="
$e = Get-WinEvent -FilterHashtable @{ LogName = 'Microsoft-Windows-CodeIntegrity/Operational'; StartTime = (Get-Date).AddDays(-7) } |
    Where-Object { $_.Message -like '*camoufox*' -or $_.Message -like '*python*' }
if ($e) { ($e | Select-Object -First 6 TimeCreated, Id | Format-Table -AutoSize | Out-String).Trim() } else { "ninguno relacionado" }

"=== 13 ACCESO DIRECTO ==="
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Camoufox Profile Manager.lnk'
if (Test-Path $lnk) {
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    "target : " + $sc.TargetPath
    "args   : " + $sc.Arguments
    "workdir: " + $sc.WorkingDirectory
} else { "NO EXISTE  <-- creado por: python install.py --shortcut-only" }

"=== FIN ==="
