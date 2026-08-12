param(
    [string]$Submission = ".tmp/hku/lab-b-submission.json"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$submissionPath = (Resolve-Path (Join-Path $repositoryRoot $Submission)).Path
$record = Get-Content -Raw -LiteralPath $submissionPath | ConvertFrom-Json
$jobId = [string]$record.job_id
if ($jobId -notmatch "^[0-9]+$") {
    throw "Submission record contains an invalid Slurm Job ID"
}
$remoteArtifacts = "/userhome/cs2/u3665453/AgentLadder/artifacts/lab-b-tiny-pretrain/job-$jobId"
if ([string]$record.remote_artifacts -ne $remoteArtifacts) {
    throw "Submission record artifact path is outside the expected job path"
}

$active = @(ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -h -j '$jobId' -o '%i|%T|%M|%R'")
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the exact Slurm job"
}
if ($active.Count -gt 0 -and ($active -join "").Trim()) {
    $active
    throw "The Slurm job is still active; reports are not ready"
}

$remoteVerification = ssh -o BatchMode=yes hku-gpu2 "cd '$remoteArtifacts' && grep -q 'LAB_B_REMOTE_GATE=PASS' /userhome/cs2/u3665453/AgentLadder/logs/lab-b-$jobId.log && sha256sum -c checksums.sha256 && cat checksums.sha256"
if ($LASTEXITCODE -ne 0) {
    $remoteVerification
    throw "Remote gate marker or artifact checksum verification failed"
}
$remoteVerification

$stageRoot = Join-Path $repositoryRoot ".remote_artifacts_stage/lab-b-tiny-pretrain/job-$jobId"
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null
$textArtifacts = @(
    "manifest.json",
    "lab-b-tiny-pretrain.json",
    "lab-b-tiny-pretrain.md",
    "slurm.json",
    "run-request.json",
    "pretrain.stdout.json",
    "training-tests.log",
    "full-tests.log",
    "checksums.sha256"
)
foreach ($name in $textArtifacts) {
    scp "hku-gpu2:$remoteArtifacts/$name" (Join-Path $stageRoot $name)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download $name into the staging directory"
    }
}
scp "hku-gpu2:/userhome/cs2/u3665453/AgentLadder/logs/lab-b-$jobId.log" (Join-Path $stageRoot "slurm.log")
if ($LASTEXITCODE -ne 0) {
    throw "Failed to download the Slurm log"
}

$expected = @{}
foreach ($line in Get-Content -LiteralPath (Join-Path $stageRoot "checksums.sha256")) {
    if ($line -match "^([0-9a-f]{64})\s+(.+)$") {
        $expected[$Matches[2].Trim()] = $Matches[1]
    }
}
foreach ($name in $textArtifacts | Where-Object { $_ -ne "checksums.sha256" }) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $stageRoot $name) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected[$name] -ne $actual) {
        throw "Downloaded artifact hash mismatch: $name"
    }
}

$report = Get-Content -Raw -LiteralPath (Join-Path $stageRoot "lab-b-tiny-pretrain.json") | ConvertFrom-Json
if (-not $report.passed) {
    throw "Downloaded Lab B report does not pass"
}
$failedChecks = @($report.checks.PSObject.Properties | Where-Object { -not $_.Value })
if ($failedChecks.Count -gt 0) {
    throw "Downloaded Lab B report contains failed checks"
}

ssh -o BatchMode=yes hku-gpu2 "squeue -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'; ps -u u3665453 -o pid,etime,cmd | grep -E 'python|torchrun|accelerate|srun' | grep -v grep || true"
if ($LASTEXITCODE -ne 0) {
    throw "Final account timing/process check failed"
}

[ordered]@{
    job_id = $jobId
    local_stage = $stageRoot
    report_passed = $true
    checkpoint_location = "$remoteArtifacts/tiny_dense.pt"
    checkpoint_downloaded = $false
} | ConvertTo-Json
