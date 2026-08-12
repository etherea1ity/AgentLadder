param([string]$PackageResult = ".tmp/hku/package-result.json")

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$packageResultPath = (Resolve-Path (Join-Path $repositoryRoot $PackageResult)).Path
$package = Get-Content -Raw -LiteralPath $packageResultPath | ConvertFrom-Json
$archivePath = (Resolve-Path $package.archive).Path
$bundleHash = [string]$package.sha256
$parentCommit = [string]$package.parent_commit
if ($bundleHash -notmatch "^[0-9a-f]{64}$" -or $parentCommit -notmatch "^[0-9a-f]{40}$") {
    throw "Package result contains malformed lineage"
}
if ((Get-FileHash $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $bundleHash) {
    throw "Local source archive changed after packaging"
}

$remoteRoot = "/userhome/cs2/u3665453/AgentLadder"
$remoteArchive = "$remoteRoot/incoming/source-$bundleHash.tar.gz"
$remoteDeployment = "$remoteRoot/deployments/$bundleHash"
$baseCheckpoint = "$remoteRoot/artifacts/lab-b-tiny-pretrain/job-133910/tiny_dense.pt"
$baseHash = "ea885bc2e6cb5aebacb576b85c1c61876a711962842a9e1ac84a1f677895d9f3"
$identity = @(ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "hostname; id -un; pwd")
if ($LASTEXITCODE -ne 0 -or $identity.Count -lt 3 -or $identity[1].Trim() -ne "u3665453" -or $identity[2].Trim() -ne "/userhome/cs2/u3665453") {
    throw "HKU SSH identity did not match the handoff contract"
}
$existingJobs = @(ssh -o BatchMode=yes hku-gpu2 "squeue -h -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the Slurm queue" }
if ($existingJobs.Count -gt 0 -and ($existingJobs -join "").Trim()) {
    $existingJobs
    throw "Refusing to submit while this account already has an active job"
}
$preflight = ssh -o BatchMode=yes hku-gpu2 "squeue -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'; quota -s 2>/dev/null || true; df -h /userhome/cs2/u3665453 | tail -n 1; echo '$baseHash  $baseCheckpoint' | sha256sum -c -; if [ -e '$remoteArchive' ] || [ -e '$remoteDeployment' ]; then echo TARGET_EXISTS; exit 17; fi"
if ($LASTEXITCODE -ne 0) { $preflight; throw "Remote preflight failed" }
$preflight
ssh -o BatchMode=yes hku-gpu2 "mkdir -p '$remoteRoot/incoming' '$remoteRoot/deployments' '$remoteRoot/logs' '$remoteRoot/artifacts/lab-c-trajectory-distillation'"
if ($LASTEXITCODE -ne 0) { throw "Could not create scoped Lab C directories" }
scp $archivePath "hku-gpu2:$remoteArchive"
if ($LASTEXITCODE -ne 0) { throw "Source archive upload failed" }
$remoteHash = (ssh -o BatchMode=yes hku-gpu2 "sha256sum '$remoteArchive' | awk '{print `$1}'").Trim()
if ($LASTEXITCODE -ne 0 -or $remoteHash -ne $bundleHash) { throw "Remote archive hash mismatch" }
ssh -o BatchMode=yes hku-gpu2 "mkdir '$remoteDeployment' && tar -xzf '$remoteArchive' -C '$remoteDeployment' && test -f '$remoteDeployment/scripts/hku/lab_c_trajectory_distillation.sbatch'"
if ($LASTEXITCODE -ne 0) { throw "Remote deployment extraction failed" }
ssh -o BatchMode=yes hku-gpu2 "cd '$remoteDeployment' && AGENTLADDER_SOURCE_DIR='$remoteDeployment' bash scripts/hku/bootstrap_agentladder.sh"
if ($LASTEXITCODE -ne 0) { throw "Remote isolated environment bootstrap failed" }
$exports = "ALL,AGENTLADDER_SOURCE_DIR=$remoteDeployment,AGENTLADDER_SOURCE_BUNDLE_SHA256=$bundleHash,AGENTLADDER_PARENT_COMMIT=$parentCommit"
$jobId = (ssh -o BatchMode=yes hku-gpu2 "cd '$remoteDeployment' && sbatch --parsable --export='$exports' scripts/hku/lab_c_trajectory_distillation.sbatch").Trim()
if ($LASTEXITCODE -ne 0 -or $jobId -notmatch "^[0-9]+$") { throw "Invalid Slurm Job ID: $jobId" }
$submission = [ordered]@{
    schema_version = "klara.hku-submission.v1"
    job_id = $jobId
    source_bundle_sha256 = $bundleHash
    parent_commit = $parentCommit
    remote_deployment = $remoteDeployment
    remote_log = "$remoteRoot/logs/lab-c-$jobId.log"
    remote_artifacts = "$remoteRoot/artifacts/lab-c-trajectory-distillation/job-$jobId"
}
$output = Join-Path (Split-Path $packageResultPath) "lab-c-submission.json"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($output, (($submission | ConvertTo-Json) + "`n"), $utf8)
$submission | ConvertTo-Json
