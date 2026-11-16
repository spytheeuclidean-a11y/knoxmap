# Build KnoxMap.exe with MSVC, the way Windows software is normally built.
#
#     win\build_launcher.ps1 [version]
#
# win/build_launcher.sh builds the same launcher with mingw-w64 and is what to
# use on Linux. This is what the release uses, for one reason: antivirus.
#
# The launcher is a small stripped binary whose whole job is two
# CreateProcessW calls, which is structurally what a dropper is, and mingw-w64
# output is heavily over-represented in the malware corpora the heuristics are
# trained on. Built with the toolchain the rest of Windows software uses, the
# same code stops looking like the thing it is not. None of this is a
# substitute for signing it - that is the only real fix - but it is free.
#
# Symbols are left in for the same reason: a tiny binary with everything
# stripped out of it reads as something with something to hide, and 30 KB is
# not worth it.
[CmdletBinding()]
param([string]$Version = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Version) {
    # The version the window reports, which is the first heading in the
    # changelog - the same rule knoxlog.version() follows.
    foreach ($line in Get-Content "CHANGELOG.md") {
        if ($line -match '^##\s+(\d[\d.]*)') { $Version = $Matches[1]; break }
    }
}
if (-not $Version) { throw "no version in CHANGELOG.md and none given" }
$parts = $Version.Split(".")
$major = if ($parts.Count -gt 0 -and $parts[0]) { $parts[0] } else { "0" }
$minor = if ($parts.Count -gt 1 -and $parts[1]) { $parts[1] } else { "0" }
$patch = if ($parts.Count -gt 2 -and $parts[2]) { $parts[2] } else { "0" }
$build = if ($parts.Count -gt 3 -and $parts[3] -and [int]$parts[3] -le 65535) { $parts[3] } else { "0" }

# The compiler, from whatever Visual Studio or Build Tools is installed. This
# uses only what ships on the machine, so the release does not depend on a
# third-party action to set the environment up.
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { throw "Visual Studio Build Tools are not installed" }
    # '*' quoted: unquoted, PowerShell offers it to the path expander first.
    $vs = & $vswhere -latest -products '*' `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    if (-not $vs) { throw "no Visual Studio with the C++ tools in it" }
    Import-Module (Join-Path $vs "Common7\Tools\Microsoft.VisualStudio.DevShell.dll")
    # 2>$null: VsDevCmd.bat calls vswhere without a path of its own on a
    # Build Tools install and says so on stderr. It sets the environment up
    # regardless - cl.exe is there afterwards - and a CI log should not carry
    # a message that looks like a failure and is not one.
    Enter-VsDevShell -VsInstallPath $vs -SkipAutomaticLocation `
        -DevCmdArguments "-arch=x64 -host_arch=x64" 2>$null | Out-Null
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw "the Visual Studio environment did not bring cl.exe with it"
    }
    Set-Location $root
}

$work = Join-Path ([System.IO.Path]::GetTempPath()) ("knoxmap-launcher-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force $work | Out-Null
try {
    # The icon and the details Windows shows in the file's properties. An
    # unsigned exe with none of this is a nameless binary, which is exactly
    # what people are right to be wary of.
    (Get-Content "win\knoxmap.rc" -Raw).
        Replace("@MAJOR@", $major).Replace("@MINOR@", $minor).
        Replace("@PATCH@", $patch).Replace("@BUILD@", $build).
        Replace("@VERSION@", $Version) |
        Set-Content -Encoding ascii (Join-Path $work "knoxmap.rc")

    # The .rc names branding/knoxmap.ico relative to the repository root.
    & rc.exe /nologo /i "$root" /fo (Join-Path $work "knoxmap.res") `
        (Join-Path $work "knoxmap.rc")
    if ($LASTEXITCODE -ne 0) { throw "rc.exe failed" }

    # /DUNICODE and wWinMainCRTStartup are what -municode is to mingw;
    # /SUBSYSTEM:WINDOWS is -mwindows, so it opens no console of its own.
    # _CRT_SECURE_NO_WARNINGS: the launcher uses wcscpy and _snwprintf on
    # buffers it sized itself, and MSVC's _s suggestions are not available to
    # the mingw build that has to keep compiling from the same source.
    & cl.exe /nologo /O2 /W4 /DUNICODE /D_UNICODE /D_CRT_SECURE_NO_WARNINGS `
        /Fe:"$root\KnoxMap.exe" /Fo:"$work\\" `
        "win\knoxmap_launcher.c" (Join-Path $work "knoxmap.res") `
        /link /SUBSYSTEM:WINDOWS /ENTRY:wWinMainCRTStartup user32.lib
    if ($LASTEXITCODE -ne 0) { throw "cl.exe failed" }
} finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

Write-Host "built KnoxMap.exe for KnoxMap $Version"
