param(
    [string]$PackageResult = ".tmp/hku/package-result.json"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$packageResultPath = (Resolve-Path (Join-Path $repositoryRoot $PackageResult)).Path
$package = Get-Content -Raw -LiteralPath $packageResultPath | ConvertFrom-Json
$archivePath = (Resolve-Path $package.archive).Path
$bundleHash = [string]$package.sha256
$parentCommit = [string]$package.parent_commit

if ($bundleHash -notmatch "^[0-9a-f]{64}$") {
    throw "Package result contains a malformed SHA-256"
}
if ($parentCommit -notmatch "^[0-9a-f]{40}$") {
    throw "Package result contains a malformed parent commit"
}
$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $bundleHash) {
    throw "Local source archive changed after packaging"
}

$remoteRoot = "/userhome/cs2/u3665453/AgentLadder"
$remoteArchive = "$remoteRoot/incoming/source-$bundleHash.tar.gz"
$remoteDeployment = "$remoteRoot/deployments/$bundleHash"

$identity = ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "hostname; id -un; pwd"
if ($LASTEXITCODE -ne 0) {
    throw "HKU SSH readiness check failed"
}
$identityLines = @($identity)
if ($identityLines.Count -lt 3 -or $identityLines[1].Trim() -ne "u3665453" -or $identityLines[2].Trim() -ne "/userhome/cs2/u3665453") {
    throw "HKU SSH identity did not match the handoff contract"
}

$existingJobs = @(ssh -o BatchMode=yes hku-gpu2 "squeue -h -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'")
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the existing Slurm queue"
}
if ($existingJobs.Count -gt 0 -and ($existingJobs -join "").Trim()) {
    $existingJobs
    throw "Refusing to submit while this account already has a RUNNING or PENDING job"
}

$preflight = ssh -o BatchMode=yes hku-gpu2 "squeue -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'; quota -s 2>/dev/null || true; df -h /userhome/cs2/u3665453 | tail -n 1; if [ -e '$remoteArchive' ] || [ -e '$remoteDeployment' ]; then echo TARGET_EXISTS; exit 17; fi; find '$remoteRoot' -mindepth 1 -maxdepth 2 -printf '%p|%y\n' 2>/dev/null | sort | head -n 200"
if ($LASTEXITCODE -ne 0) {
    $preflight
    throw "Remote preflight failed or the hash-named target already exists"
}
$preflight

ssh -o BatchMode=yes hku-gpu2 "mkdir -p '$remoteRoot/incoming' '$remoteRoot/deployments' '$remoteRoot/logs' '$remoteRoot/artifacts/lab-b-tiny-pretrain'"
if ($LASTEXITCODE -ne 0) {
    throw "Could not create scoped AgentLadder remote directories"
}
scp $archivePath "hku-gpu2:$remoteArchive"
if ($LASTEXITCODE -ne 0) {
    throw "Source archive upload failed"
}

$remoteHash = (ssh -o BatchMode=yes hku-gpu2 "sha256sum '$remoteArchive' | awk '{print `$1}'").Trim()
if ($LASTEXITCODE -ne 0 -or $remoteHash -ne $bundleHash) {
    throw "Remote source archive SHA-256 did not match"
}

ssh -o BatchMode=yes hku-gpu2 "mkdir '$remoteDeployment' && tar -xzf '$remoteArchive' -C '$remoteDeployment' && test -f '$remoteDeployment/pyproject.toml' && test -f '$remoteDeployment/scripts/hku/lab_b_tiny_pretrain.sbatch'"
if ($LASTEXITCODE -ne 0) {
    throw "Remote deployment extraction failed"
}

ssh -o BatchMode=yes hku-gpu2 "cd '$remoteDeployment' && AGENTLADDER_SOURCE_DIR='$remoteDeployment' bash scripts/hku/bootstrap_agentladder.sh"
if ($LASTEXITCODE -ne 0) {
    throw "Remote isolated environment bootstrap failed"
}

$exportValues = "ALL,AGENTLADDER_SOURCE_DIR=$remoteDeployment,AGENTLADDER_SOURCE_BUNDLE_SHA256=$bundleHash,AGENTLADDER_PARENT_COMMIT=$parentCommit"
$jobId = (ssh -o BatchMode=yes hku-gpu2 "cd '$remoteDeployment' && sbatch --parsable --export='$exportValues' scripts/hku/lab_b_tiny_pretrain.sbatch").Trim()
if ($LASTEXITCODE -ne 0 -or $jobId -notmatch "^[0-9]+$") {
    throw "Slurm submission failed or returned an invalid Job ID: $jobId"
}

$submission = [ordered]@{
    schema_version = "klara.hku-submission.v1"
    job_id = $jobId
    source_bundle_sha256 = $bundleHash
    parent_commit = $parentCommit
    remote_deployment = $remoteDeployment
    remote_log = "$remoteRoot/logs/lab-b-$jobId.log"
    remote_artifacts = "$remoteRoot/artifacts/lab-b-tiny-pretrain/job-$jobId"
}
$submissionPath = Join-Path (Split-Path $packageResultPath) "lab-b-submission.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    $submissionPath,
    (($submission | ConvertTo-Json) + "`n"),
    $utf8NoBom
)
$submission | ConvertTo-Json
