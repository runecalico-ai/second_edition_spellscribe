[CmdletBinding()]
param(
    [ValidateSet("Standard", "Pro", "All")]
    [string]$Flavor = "All",
    [switch]$ProbeOnly,
    [switch]$SkipPyInstaller,
    [switch]$SkipInstaller,
    [switch]$RequireInstaller,
    [switch]$DryRun,
    [switch]$Clean,
    [switch]$RequireTrustedTesseract
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($RequireInstaller -and $SkipInstaller) {
    throw "Cannot combine -RequireInstaller with -SkipInstaller."
}

function Get-RegistryTesseractInstallDirs {
    [OutputType([string[]])]
    param()

    $registryPaths = @(
        "HKLM:\SOFTWARE\Tesseract-OCR",
        "HKLM:\SOFTWARE\WOW6432Node\Tesseract-OCR",
        "HKCU:\SOFTWARE\Tesseract-OCR"
    )
    $dirs = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($registryPath in $registryPaths) {
        if (-not (Test-Path -LiteralPath $registryPath)) {
            continue
        }

        $key = Get-ItemProperty -LiteralPath $registryPath -ErrorAction SilentlyContinue
        if ($null -eq $key) {
            continue
        }

        foreach ($propertyName in @("InstallDir", "Path")) {
            $candidate = $key.$propertyName
            if (
                -not [string]::IsNullOrWhiteSpace($candidate) -and
                (Test-Path -LiteralPath $candidate -PathType Container) -and
                $seen.Add($candidate)
            ) {
                $dirs.Add($candidate)
            }
        }
    }

    return $dirs.ToArray()
}

function Get-TesseractVersion {
    [OutputType([Version])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath
    )

    $versionLine = & $ExecutablePath --version 2>$null | Select-Object -First 1
    if (-not $versionLine) {
        return $null
    }

    $match = [regex]::Match($versionLine, '^tesseract\s+v?([0-9]+(?:\.[0-9]+){1,3})\b')
    if (-not $match.Success) {
        return $null
    }

    return [Version]$match.Groups[1].Value
}

function Get-ExecutableTrustInfo {
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ExecutablePath,
        [Parameter(Mandatory = $true)]
        [bool]$RequireTrustedSignature
    )

    $isWindowsHost = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([System.Runtime.InteropServices.OSPlatform]::Windows)
    if (-not $isWindowsHost) {
        return @{
            IsTrusted = $true
            Status = "NotCheckedNonWindows"
            Signer = "<not-applicable>"
            Detail = "Authenticode trust verification is only enforced on Windows hosts."
        }
    }

    if (-not (Get-Command -Name "Get-AuthenticodeSignature" -ErrorAction SilentlyContinue)) {
        if ($RequireTrustedSignature) {
            throw "Cannot enforce -RequireTrustedTesseract for '$ExecutablePath' because Get-AuthenticodeSignature is unavailable on this host."
        }

        return @{
            IsTrusted = $false
            Status = "NotCheckedMissingCapability"
            Signer = "<unknown>"
            Detail = "Authenticode trust check unavailable because Get-AuthenticodeSignature is not present on this host."
        }
    }

    $signature = Get-AuthenticodeSignature -FilePath $ExecutablePath
    $status = [string]$signature.Status
    $signer = if ($null -ne $signature.SignerCertificate) {
        $signature.SignerCertificate.Subject
    } else {
        "<unsigned>"
    }
    $isTrusted = $signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid

    return @{
        IsTrusted = $isTrusted
        Status = $status
        Signer = $signer
        Detail = "Authenticode status '$status'; signer '$signer'."
    }
}

function Get-TesseractSearchCandidates {
    [OutputType([hashtable[]])]
    param()

    $candidates = [System.Collections.Generic.List[hashtable]]::new()
    $seenExePaths = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    $programFiles = $env:ProgramFiles
    $programFilesX86 = ${env:ProgramFiles(x86)}
    $localProgramsRoot = Join-Path $env:LocalAppData "Programs"

    $rootCandidates = @()
    foreach ($root in @($programFiles, $programFilesX86)) {
        if (-not [string]::IsNullOrWhiteSpace($root) -and [System.IO.Path]::IsPathRooted($root)) {
            $rootCandidates += (Join-Path $root "Tesseract-OCR")
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($localProgramsRoot) -and [System.IO.Path]::IsPathRooted($localProgramsRoot)) {
        $rootCandidates += (Join-Path $localProgramsRoot "Tesseract-OCR")
    }

    $chocolateyRoot = $env:ChocolateyInstall
    $hasChocolateyRoot = -not [string]::IsNullOrWhiteSpace($chocolateyRoot)
    $hasUsableChocolateyRoot = $hasChocolateyRoot -and [System.IO.Path]::IsPathRooted($chocolateyRoot)
    if ($hasUsableChocolateyRoot) {
        $rootCandidates += (Join-Path $chocolateyRoot "lib\tesseract\tools")
    }

    foreach ($root in $rootCandidates) {
        if (-not [string]::IsNullOrWhiteSpace($root)) {
            $exePath = Join-Path $root "tesseract.exe"
            if ($seenExePaths.Add($exePath)) {
                $candidates.Add(@{
                    Source = "KnownRoot"
                    Hint = $root
                    ExePath = $exePath
                })
            }
        }
    }

    $pathCommands = @(Get-Command "tesseract.exe" -ErrorAction SilentlyContinue -All)
    foreach ($command in $pathCommands) {
        if ($null -eq $command -or [string]::IsNullOrWhiteSpace($command.Source)) {
            continue
        }

        if ($seenExePaths.Add($command.Source)) {
            $candidates.Add(@{
                Source = "PATH"
                Hint = Split-Path -Parent $command.Source
                ExePath = $command.Source
            })
        }
    }

    foreach ($registryDir in Get-RegistryTesseractInstallDirs) {
        $exePath = Join-Path $registryDir "tesseract.exe"
        if ($seenExePaths.Add($exePath)) {
            $candidates.Add(@{
                Source = "Registry"
                Hint = $registryDir
                ExePath = $exePath
            })
        }
    }

    return $candidates.ToArray()
}

function Resolve-TesseractBundleInputs {
    [OutputType([hashtable])]
    param()

    $requiredVersion = [Version]"5.5.0"
    $checkedLocations = [System.Collections.Generic.List[string]]::new()
    $rejectedUntrusted = [System.Collections.Generic.List[string]]::new()
    $bundleReadyCandidates = [System.Collections.Generic.List[hashtable]]::new()

    foreach ($candidate in Get-TesseractSearchCandidates) {
        $exePath = $candidate.ExePath
        $checkedLocations.Add("$($candidate.Source): $exePath")

        if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
            continue
        }

        $trust = Get-ExecutableTrustInfo -ExecutablePath $exePath -RequireTrustedSignature $RequireTrustedTesseract
        $version = Get-TesseractVersion -ExecutablePath $exePath
        if ($null -eq $version) {
            continue
        }

        if ($version.Major -ne $requiredVersion.Major -or $version.Minor -ne $requiredVersion.Minor) {
            continue
        }

        $tessdataCandidates = @(
            (Join-Path (Split-Path -Parent $exePath) "tessdata"),
            (Join-Path (Split-Path -Parent (Split-Path -Parent $exePath)) "tessdata")
        ) | Select-Object -Unique

        foreach ($tessdataDir in $tessdataCandidates) {
            $engPath = Join-Path $tessdataDir "eng.traineddata"
            if (Test-Path -LiteralPath $engPath -PathType Leaf) {
                if ($RequireTrustedTesseract -and -not $trust.IsTrusted) {
                    $rejectedUntrusted.Add("$($candidate.Source): $exePath [$($trust.Status)] signer=$($trust.Signer)")
                    break
                }

                $bundleReadyCandidates.Add(@{
                    Source = $candidate.Source
                    ExePath = $exePath
                    TesseractDir = Split-Path -Parent $exePath
                    TessdataDir = $tessdataDir
                    EngTrainedData = $engPath
                    TesseractVersion = $version.ToString()
                    Version = $version
                    SignatureTrusted = $trust.IsTrusted
                    SignatureStatus = $trust.Status
                    SignatureSigner = $trust.Signer
                    SignatureDetail = $trust.Detail
                })
                break
            }
        }
    }

    if ($bundleReadyCandidates.Count -eq 0) {
        $searchedLocations = $checkedLocations.ToArray()
        if ($searchedLocations.Count -eq 0) {
            $searchedLocations = @("<no candidate locations generated>")
        }

        $untrustedLocations = $rejectedUntrusted.ToArray()
        $untrustedBlock = if ($untrustedLocations.Count -gt 0) {
            "Rejected untrusted executables:`n  - $($untrustedLocations -join "`n  - ")"
        } else {
            "Rejected untrusted executables: <none>"
        }

        throw @"
Unable to locate a bundle-ready Tesseract install.
Expected:
  - tesseract.exe at version 5.5.x
  - eng.traineddata in a sibling tessdata directory
  - Authenticode status Valid when running on Windows when -RequireTrustedTesseract is enabled
Checked locations:
  - $($searchedLocations -join "`n  - ")
$untrustedBlock
Install Tesseract 5.5.x and ensure english language data is installed.
"@
    }

    $primaryCandidate = $bundleReadyCandidates |
        Sort-Object -Property ExePath, TessdataDir, Source |
        Select-Object -First 1

    return @{
        TesseractExe = $primaryCandidate.ExePath
        TesseractDir = $primaryCandidate.TesseractDir
        TessdataDir = $primaryCandidate.TessdataDir
        EngTrainedData = $primaryCandidate.EngTrainedData
        TesseractVersion = $primaryCandidate.Version.ToString()
        SignatureTrusted = $primaryCandidate.SignatureTrusted
        SignatureStatus = $primaryCandidate.SignatureStatus
        SignatureSigner = $primaryCandidate.SignatureSigner
        SignatureDetail = $primaryCandidate.SignatureDetail
        BundleReadyCandidates = @($bundleReadyCandidates.ToArray() |
            Sort-Object -Property ExePath, TessdataDir, Source |
            ForEach-Object {
                [pscustomobject]@{
                    Source = $_.Source
                    ExePath = $_.ExePath
                    TesseractDir = $_.TesseractDir
                    TessdataDir = $_.TessdataDir
                    EngTrainedData = $_.EngTrainedData
                    TesseractVersion = $_.TesseractVersion
                    SignatureTrusted = $_.SignatureTrusted
                    SignatureStatus = $_.SignatureStatus
                    SignatureSigner = $_.SignatureSigner
                }
            })
    }
}

function Resolve-AppIcon {
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $iconCandidates = @(
        (Join-Path $RepoRoot "resources\icons\spellscribe.ico"),
        (Join-Path $RepoRoot "resources\icons\app.ico"),
        (Join-Path $RepoRoot "build\icon.ico")
    )

    foreach ($iconPath in $iconCandidates) {
        if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
            return $iconPath
        }
    }

    throw "Could not find application icon. Expected one of: $($iconCandidates -join ', ')"
}

function Resolve-LicenseFile {
    [OutputType([string])]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $licensePath = Join-Path $RepoRoot "resources\license.txt"
    if (-not (Test-Path -LiteralPath $licensePath -PathType Leaf)) {
        throw "Missing installer license file: $licensePath"
    }

    return $licensePath
}

function Invoke-ExternalCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$Required
    )

    $resolved = Get-Command -Name $CommandName -ErrorAction SilentlyContinue
    if ($null -eq $resolved) {
        $message = "Tool '$CommandName' was not found in PATH."
        if ($Required) {
            throw $message
        }

        Write-Warning "$message Skipping this step."
        return $false
    }

    $display = "$CommandName " + ($Arguments -join " ")
    if ($DryRun) {
        Write-Host "[dry-run] $display"
        return $true
    }

    Write-Host "> $display"
    & $resolved.Source @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $display"
    }

    return $true
}

$scriptRoot = Split-Path -Parent $PSCommandPath
$repoRoot = Split-Path -Parent $scriptRoot
$bundleInfo = Resolve-TesseractBundleInputs
$iconPath = Resolve-AppIcon -RepoRoot $repoRoot

Write-Host "SpellScribe packaging prerequisites:"
Write-Host "Bundle prerequisites resolved:"
Write-Host "  Tesseract: $($bundleInfo.TesseractExe) (v$($bundleInfo.TesseractVersion))"
Write-Host "  Tessdata : $($bundleInfo.TessdataDir)"
Write-Host "  eng data : $($bundleInfo.EngTrainedData)"
Write-Host "  Signature: $($bundleInfo.SignatureStatus) (trusted=$($bundleInfo.SignatureTrusted); signer=$($bundleInfo.SignatureSigner))"
Write-Host "  Icon     : $iconPath"
Write-Host "  Selected : deterministic primary from $($bundleInfo.BundleReadyCandidates.Count) bundle-ready candidate(s)"

if (-not $bundleInfo.SignatureTrusted) {
    Write-Warning "Using an untrusted Tesseract binary. Signature status is '$($bundleInfo.SignatureStatus)' for '$($bundleInfo.TesseractExe)'. Use -RequireTrustedTesseract to enforce trusted-only detection."
}

if ($ProbeOnly) {
    Write-Host "Probe complete. No build steps executed."
    exit 0
}

$specByFlavor = @{
    Standard = Join-Path $scriptRoot "spell_scribe_std.spec"
    Pro = Join-Path $scriptRoot "spell_scribe_pro.spec"
}

$selectedFlavors = switch ($Flavor) {
    "Standard" { @("Standard") }
    "Pro" { @("Pro") }
    default { @("Standard", "Pro") }
}

foreach ($selectedFlavor in $selectedFlavors) {
    $specPath = $specByFlavor[$selectedFlavor]
    if (-not (Test-Path -LiteralPath $specPath -PathType Leaf)) {
        throw "Missing PyInstaller spec for flavor '$selectedFlavor': $specPath"
    }
}

$env:SPELLSCRIBE_TESSERACT_DIR = $bundleInfo.TesseractDir
$env:SPELLSCRIBE_TESSDATA_DIR = $bundleInfo.TessdataDir
$env:SPELLSCRIBE_APP_ICON = $iconPath

if (-not $SkipPyInstaller) {
    foreach ($selectedFlavor in $selectedFlavors) {
        $specPath = $specByFlavor[$selectedFlavor]
        $env:SPELLSCRIBE_BUILD_FLAVOR = $selectedFlavor
        $pyinstallerArgs = @("--noconfirm")
        if ($Clean) {
            $pyinstallerArgs += "--clean"
        }
        $pyinstallerArgs += $specPath

        Write-Host "Building $selectedFlavor flavor with spec '$specPath'"
        [void](Invoke-ExternalCommand -CommandName "pyinstaller" -Arguments $pyinstallerArgs -Required)
    }
} else {
    Write-Host "Skipping PyInstaller build steps (-SkipPyInstaller)."
}

$installerScriptPath = Join-Path $scriptRoot "installer.iss"
if ($SkipInstaller) {
    Write-Host "Skipping Inno Setup build steps (-SkipInstaller)."
} else {
    if (-not (Test-Path -LiteralPath $installerScriptPath -PathType Leaf)) {
        $missingScriptMessage = "Installer script not found at '$installerScriptPath'."
        if ($RequireInstaller) {
            throw $missingScriptMessage
        }

        Write-Warning "$missingScriptMessage Skipping Inno Setup build steps. Use -RequireInstaller to make this a hard failure."
    } else {
        $licensePath = Resolve-LicenseFile -RepoRoot $repoRoot
        $env:SPELLSCRIBE_LICENSE_FILE = $licensePath
        Write-Host "Resolved installer license: $licensePath"

        foreach ($selectedFlavor in $selectedFlavors) {
            $isccArgs = @(
                "/Q"
                "/DAppFlavor=$selectedFlavor"
                "/DRepoRoot=$repoRoot"
                "/DLicenseFile=$licensePath"
                $installerScriptPath
            )
            Write-Host "Building installer for $selectedFlavor flavor"
            $didRunInstaller = Invoke-ExternalCommand -CommandName "iscc" -Arguments $isccArgs -Required:$RequireInstaller
            if (-not $didRunInstaller) {
                break
            }
        }
    }
}

Write-Host "Build orchestration complete."
