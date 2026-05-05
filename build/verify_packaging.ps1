[CmdletBinding()]
param(
    [ValidateSet("Standard", "Pro", "Installer", "All")]
    [string[]]$Checks = @("All"),
    [string]$RepoRoot = "",
    [switch]$Strict,
    [switch]$SmokeExe,
    [int]$SmokeWaitSeconds = 6
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
}

function Test-Include {
    param(
        [string[]]$Wanted,
        [ValidateSet("Standard", "Pro", "Installer", "All")]
        [string]$Name
    )

    if ($Wanted -contains "All") {
        return $true
    }

    return ($Wanted -contains $Name)
}

function Assert-StandardBundleHasNoHeavyMl {
    param(
        [string]$Root,
        [bool]$StrictMode
    )

    $dist = Join-Path $Root "dist\SpellScribe-Standard"
    if (-not (Test-Path -LiteralPath $dist)) {
        $msg = "Standard onedir not found at '$dist'. Build Standard first (omit -SkipPyInstaller) or pass -Strict:$false to warn only."
        if ($StrictMode) {
            throw $msg
        }

        Write-Warning $msg
        return
    }

    $exe = Join-Path $dist "SpellScribe-Standard.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Standard bundle exists but main executable is missing: $exe"
    }

    $segmentPattern = '(?i)(^|[\\/])(marker|marker_pdf|torch|torchvision|torchaudio|transformers|accelerate|onnxruntime|sentence_transformers)([\\/]|\.dll$)|(^|[\\/])torch_[^\\/]+\.dll$'

    $hits = [System.Collections.Generic.List[string]]::new()
    foreach ($file in Get-ChildItem -LiteralPath $dist -Recurse -File -ErrorAction Stop) {
        $rel = $file.FullName.Substring($dist.Length).TrimStart("\", "/")
        if ($rel -match $segmentPattern) {
            $hits.Add($file.FullName)
        }
    }

    if ($hits.Count -gt 0) {
        $sample = @($hits | Select-Object -First 20)
        $suffix = if ($hits.Count -gt 20) { "`n  … and $($hits.Count - 20) more" } else { "" }
        throw "Standard bundle contains forbidden ML stack paths:`n  - $($sample -join "`n  - ")$suffix"
    }

    Write-Host "Standard bundle OK: no marker/torch/transformers paths under '$dist'."
}

function Assert-ProBundleIncludesHeavyMl {
    param(
        [string]$Root,
        [bool]$StrictMode
    )

    $dist = Join-Path $Root "dist\SpellScribe-Pro"
    if (-not (Test-Path -LiteralPath $dist)) {
        $msg = "Pro onedir not found at '$dist'. Build Pro first or disable -Strict for a warning-only skip."
        if ($StrictMode) {
            throw $msg
        }

        Write-Warning $msg
        return
    }

    $exe = Join-Path $dist "SpellScribe-Pro.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Pro bundle exists but main executable is missing: $exe"
    }

    $needles = @(
        @{ Label = "marker"; Pattern = '(?i)(^|[\\/])marker([\\/]|\.dll$)' },
        @{ Label = "torch"; Pattern = '(?i)(^|[\\/])torch(\.dll|[\\/])' }
    )

    $missing = [System.Collections.Generic.List[string]]::new()
    foreach ($needle in $needles) {
        $found = $false
        foreach ($file in Get-ChildItem -LiteralPath $dist -Recurse -File -ErrorAction Stop) {
            $rel = $file.FullName.Substring($dist.Length).TrimStart("\", "/")
            if ($rel -match $needle.Pattern) {
                $found = $true
                break
            }
        }

        if (-not $found) {
            $missing.Add($needle.Label)
        }
    }

    if ($missing.Count -gt 0) {
        throw "Pro bundle missing expected heavy stack artifacts (by relative path match): $($missing -join ', ')"
    }

    Write-Host "Pro bundle OK: found marker- and torch-related files under '$dist'."
    Write-Warning "Task 5.2 CUDA/Marker runtime behavior is manual: confirm GPU stack + OCR on a CUDA machine after `ocr_backend` wiring (see README)."
}

function Assert-InstallerArtifactsExist {
    param(
        [string]$Root,
        [bool]$StrictMode
    )

    $outDir = Join-Path $Root "dist\installer"
    if (-not (Test-Path -LiteralPath $outDir)) {
        $msg = "Installer output directory missing: '$outDir'."
        if ($StrictMode) {
            throw $msg
        }

        Write-Warning $msg
        return
    }

    $setups = @(
        Get-ChildItem -LiteralPath $outDir -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "SpellScribe-*-Setup.exe" }
    )
    if ($setups.Count -eq 0) {
        $msg = "No SpellScribe-*-Setup.exe files found under '$outDir'."
        if ($StrictMode) {
            throw $msg
        }

        Write-Warning $msg
        return
    }

    Write-Host "Installer outputs OK ($($setups.Count) setup executable(s)) under '$outDir'."
    Write-Warning "Task 5.3 registry/shortcut checks remain manual (install once per flavor and verify ARP + Start Menu)."
}

function Invoke-ExeSmoke {
    param(
        [string]$ExePath,
        [int]$WaitSeconds
    )

    if (-not (Test-Path -LiteralPath $ExePath)) {
        throw "Smoke test requested but executable missing: $ExePath"
    }

    $proc = Start-Process -FilePath $ExePath -WorkingDirectory (Split-Path -Parent $ExePath) -PassThru -WindowStyle Minimized
    try {
        Start-Sleep -Seconds $WaitSeconds
        if ($proc.HasExited -and $proc.ExitCode -ne 0) {
            throw "Smoke test: '$ExePath' exited early with code $($proc.ExitCode)."
        }
    } finally {
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Host "Smoke OK: launched '$ExePath' for ${WaitSeconds}s without forcing a failure."
    Write-Warning "-SmokeExe stops the root process only; PySide6 may spawn children—use disposable VMs/hosts for repeated smokes."
}

$selected = if ($Checks.Count -eq 0) { @("All") } else { $Checks }

Write-Host "verify_packaging.ps1 using RepoRoot=$RepoRoot"

if (Test-Include -Wanted $selected -Name "Standard") {
    Assert-StandardBundleHasNoHeavyMl -Root $RepoRoot -StrictMode:$Strict
    if ($SmokeExe) {
        $smokeExePath = Join-Path $RepoRoot "dist\SpellScribe-Standard\SpellScribe-Standard.exe"
        if (-not (Test-Path -LiteralPath $smokeExePath)) {
            $smokeMsg = "Smoke test skipped: '$smokeExePath' is missing."
            if ($Strict) {
                throw $smokeMsg
            }

            Write-Warning $smokeMsg
        } else {
            Invoke-ExeSmoke -ExePath $smokeExePath -WaitSeconds $SmokeWaitSeconds
        }
    }
}

if (Test-Include -Wanted $selected -Name "Pro") {
    Assert-ProBundleIncludesHeavyMl -Root $RepoRoot -StrictMode:$Strict
    if ($SmokeExe) {
        $smokeExePath = Join-Path $RepoRoot "dist\SpellScribe-Pro\SpellScribe-Pro.exe"
        if (-not (Test-Path -LiteralPath $smokeExePath)) {
            $smokeMsg = "Smoke test skipped: '$smokeExePath' is missing."
            if ($Strict) {
                throw $smokeMsg
            }

            Write-Warning $smokeMsg
        } else {
            Invoke-ExeSmoke -ExePath $smokeExePath -WaitSeconds $SmokeWaitSeconds
        }
    }
}

if (Test-Include -Wanted $selected -Name "Installer") {
    Assert-InstallerArtifactsExist -Root $RepoRoot -StrictMode:$Strict
}

Write-Host "verify_packaging.ps1 complete."
