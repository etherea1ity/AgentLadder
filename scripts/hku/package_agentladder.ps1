param(
    [string]$OutputDirectory = ".tmp/hku"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$outputRoot = Join-Path $repositoryRoot $OutputDirectory
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$includeRoots = @(
    "apps/api",
    "config",
    "docs/reports/algorithm",
    "scripts/hku",
    "src",
    "tests"
)
$includeFiles = @(
    "apps/__init__.py",
    "pyproject.toml"
)
$forbiddenNames = @(".env", ".env.local", ".env.production", "id_rsa", "id_ed25519")
$forbiddenExtensions = @(".key", ".pem", ".ppk", ".p12", ".pfx")

function Get-RepositoryRelativePath {
    param([string]$AbsolutePath)

    $rootUri = [Uri]::new($repositoryRoot.TrimEnd("\") + "\")
    $pathUri = [Uri]::new($AbsolutePath)
    return [Uri]::UnescapeDataString($rootUri.MakeRelativeUri($pathUri).ToString())
}

$relativePaths = [System.Collections.Generic.List[string]]::new()
foreach ($root in $includeRoots) {
    $absoluteRoot = Join-Path $repositoryRoot $root
    if (-not (Test-Path $absoluteRoot)) {
        throw "Missing required package root: $root"
    }
    foreach ($file in Get-ChildItem -LiteralPath $absoluteRoot -Recurse -File) {
        $relative = Get-RepositoryRelativePath -AbsolutePath $file.FullName
        if ($relative -match "(^|/)(__pycache__|\.pytest_cache|\.tmp|node_modules)(/|$)") {
            continue
        }
        if ($relative -match "^docs/reports/algorithm/(?:lab-b-tiny-pretrain|lab-c-trajectory-distillation|lab-d-tiny-moe|lab-e-fp16-fp4)(?:\.manifest)?\.(?:json|md)$") {
            # Generated evidence is committed, but it cannot be an input to
            # the source bundle whose hash that same evidence records.
            continue
        }
        if ($forbiddenNames -contains $file.Name -or $forbiddenExtensions -contains $file.Extension.ToLowerInvariant()) {
            throw "Refusing forbidden credential-shaped path: $relative"
        }
        $relativePaths.Add($relative)
    }
}
foreach ($relative in $includeFiles) {
    $absolute = Join-Path $repositoryRoot $relative
    if (-not (Test-Path $absolute -PathType Leaf)) {
        throw "Missing required package file: $relative"
    }
    $relativePaths.Add($relative.Replace("\", "/"))
}

$relativePaths = @($relativePaths | Sort-Object -Unique)
if ($relativePaths.Count -eq 0) {
    throw "Package whitelist is empty"
}

foreach ($relative in $relativePaths) {
    $absolute = Join-Path $repositoryRoot $relative
    $text = [System.IO.File]::ReadAllText($absolute)
    if ($text -match "-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----") {
        throw "Refusing private-key content in $relative"
    }
}

$parentCommit = (git -C $repositoryRoot rev-parse HEAD).Trim()
$branch = (git -C $repositoryRoot branch --show-current).Trim()
$packagedPathSet = [System.Collections.Generic.HashSet[string]]::new(
    [string[]]$relativePaths,
    [System.StringComparer]::Ordinal
)
$dirtyPaths = @(
    git -C $repositoryRoot status --short --untracked-files=all |
        Where-Object {
            $statusPath = $_.Substring(3).Replace("\", "/")
            if ($statusPath.Contains(" -> ")) {
                $statusPath = $statusPath.Split(" -> ")[-1]
            }
            $packagedPathSet.Contains($statusPath)
        } |
        ForEach-Object {
            $statusPath = $_.Substring(3).Replace("\", "/")
            if ($statusPath.Contains(" -> ")) {
                $statusPath = $statusPath.Split(" -> ")[-1]
            }
            $statusPath
        }
)
$sourceState = [ordered]@{
    schema_version = "klara.hku-source.v1"
    branch = $branch
    parent_commit = $parentCommit
    dirty_paths = $dirtyPaths
    packaged_paths = $relativePaths.Count
}
$statePath = Join-Path $outputRoot "source-state.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    $statePath,
    (($sourceState | ConvertTo-Json -Depth 5) + "`n"),
    $utf8NoBom
)
$stateRelative = Get-RepositoryRelativePath -AbsolutePath $statePath
$allPaths = @($relativePaths + $stateRelative | Sort-Object -Unique)

$listPath = Join-Path $outputRoot "package-files.txt"
[System.IO.File]::WriteAllText(
    $listPath,
    (($allPaths -join "`n") + "`n"),
    $utf8NoBom
)
$archivePath = Join-Path $outputRoot "agentladder-gate2-source.tar.gz"
if (Test-Path $archivePath) {
    Remove-Item -LiteralPath $archivePath
}
function Convert-ToWslPath {
    param([string]$WindowsPath)

    $fullPath = [System.IO.Path]::GetFullPath($WindowsPath)
    if ($fullPath -notmatch "^([A-Za-z]):\\(.*)$") {
        throw "Unsupported Windows path for WSL conversion: $fullPath"
    }
    $drive = $Matches[1].ToLowerInvariant()
    $tail = $Matches[2].Replace("\", "/")
    return "/mnt/$drive/$tail"
}

$wslRepositoryRoot = Convert-ToWslPath -WindowsPath $repositoryRoot
$wslArchivePath = Convert-ToWslPath -WindowsPath $archivePath
$wslListPath = Convert-ToWslPath -WindowsPath $listPath
if (-not $wslRepositoryRoot -or -not $wslArchivePath -or -not $wslListPath) {
    throw "Could not translate package paths for deterministic GNU tar"
}
$tarCommand = "cd '$wslRepositoryRoot' && tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner --format=posix --pax-option=delete=atime,delete=ctime -cf - -T '$wslListPath' | gzip -n -9 > '$wslArchivePath'"
wsl bash -lc $tarCommand
if ($LASTEXITCODE -ne 0) {
    throw "deterministic GNU tar packaging failed with exit code $LASTEXITCODE"
}

$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$result = [ordered]@{
    archive = $archivePath
    sha256 = $archiveHash
    parent_commit = $parentCommit
    branch = $branch
    packaged_paths = $allPaths.Count
}
$resultPath = Join-Path $outputRoot "package-result.json"
[System.IO.File]::WriteAllText(
    $resultPath,
    (($result | ConvertTo-Json) + "`n"),
    $utf8NoBom
)
$result | ConvertTo-Json
