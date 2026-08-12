param([string]$Submission = ".tmp/hku/lab-c-submission.json")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$record = Get-Content -Raw (Resolve-Path (Join-Path $root $Submission)) | ConvertFrom-Json
$jobId = [string]$record.job_id
if ($jobId -notmatch "^[0-9]+$") { throw "Invalid Lab C Job ID" }
$remote = "/userhome/cs2/u3665453/AgentLadder/artifacts/lab-c-trajectory-distillation/job-$jobId"
if ([string]$record.remote_artifacts -ne $remote) { throw "Unexpected Lab C artifact path" }
$active = @(ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -h -j '$jobId' -o '%i|%T|%M|%R'")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect Lab C job" }
if ($active.Count -gt 0 -and ($active -join "").Trim()) { throw "Lab C is still active" }
$verification = ssh -o BatchMode=yes hku-gpu2 "cd '$remote' && grep -q 'LAB_C_REMOTE_GATE=PASS' /userhome/cs2/u3665453/AgentLadder/logs/lab-c-$jobId.log && sha256sum -c checksums.sha256 && cat checksums.sha256"
if ($LASTEXITCODE -ne 0) { $verification; throw "Lab C remote verification failed" }
$verification
$stage = Join-Path $root ".remote_artifacts_stage/lab-c-trajectory-distillation/job-$jobId"
New-Item -ItemType Directory -Force $stage | Out-Null
$files = @("manifest.json", "lab-c-trajectory-distillation.json", "lab-c-trajectory-distillation.md", "slurm.json", "run-request.json", "distillation.stdout.json", "training-tests.log", "full-tests.log", "checksums.sha256")
foreach ($name in $files) {
    scp "hku-gpu2:$remote/$name" (Join-Path $stage $name)
    if ($LASTEXITCODE -ne 0) { throw "Failed to download $name" }
}
scp "hku-gpu2:/userhome/cs2/u3665453/AgentLadder/logs/lab-c-$jobId.log" (Join-Path $stage "slurm.log")
if ($LASTEXITCODE -ne 0) { throw "Failed to download Lab C Slurm log" }
$expected = @{}
foreach ($line in Get-Content (Join-Path $stage "checksums.sha256")) {
    if ($line -match "^([0-9a-f]{64})\s+(.+)$") { $expected[$Matches[2].Trim()] = $Matches[1] }
}
foreach ($name in $files | Where-Object { $_ -ne "checksums.sha256" }) {
    $actual = (Get-FileHash (Join-Path $stage $name) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected[$name] -ne $actual) { throw "Downloaded artifact hash mismatch: $name" }
}
$report = Get-Content -Raw (Join-Path $stage "lab-c-trajectory-distillation.json") | ConvertFrom-Json
if (-not $report.passed -or @($report.checks.PSObject.Properties | Where-Object { -not $_.Value }).Count) { throw "Lab C report failed" }
ssh -o BatchMode=yes hku-gpu2 "squeue -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'; ps -u u3665453 -o pid,etime,cmd | grep -E 'python|torchrun|accelerate|srun' | grep -v grep || true"
if ($LASTEXITCODE -ne 0) { throw "Final Lab C process check failed" }
[ordered]@{
    job_id = $jobId
    local_stage = $stage
    report_passed = $true
    checkpoint_location = "$remote/tiny_distilled.pt"
    checkpoint_downloaded = $false
} | ConvertTo-Json
