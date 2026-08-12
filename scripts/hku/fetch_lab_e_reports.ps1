param([string]$Submission = ".tmp/hku/lab-e-submission.json")
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$record = Get-Content -Raw (Resolve-Path (Join-Path $root $Submission)) | ConvertFrom-Json
$job = [string]$record.job_id
if ($job -notmatch '^[0-9]+$') { throw 'Invalid Job ID' }
$remote = "/userhome/cs2/u3665453/AgentLadder/artifacts/lab-e-fp16-fp4/job-$job"
if ([string]$record.remote_artifacts -ne $remote) { throw 'Unexpected artifact path' }
$active = @(ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -h -j '$job' -o '%i|%T|%M|%R'")
if ($LASTEXITCODE -ne 0) { throw 'Queue check failed' }
if ($active.Count -gt 0 -and ($active -join '').Trim()) { throw 'Lab E active' }
$state = (ssh -o BatchMode=yes hku-gpu2 "scontrol show job '$job' -o").Trim()
if ($LASTEXITCODE -ne 0 -or $state -notmatch 'JobState=COMPLETED' -or $state -notmatch 'ExitCode=0:0') { throw "Lab E Slurm failure: $state" }
$verify = ssh -o BatchMode=yes hku-gpu2 "cd '$remote' && grep -q 'LAB_E_REMOTE_GATE=PASS' /userhome/cs2/u3665453/AgentLadder/logs/lab-e-$job.log && sha256sum -c checksums.sha256 && cat checksums.sha256"
if ($LASTEXITCODE -ne 0) { $verify; throw 'Remote verification failed' }
$verify
$stage = Join-Path $root ".remote_artifacts_stage/lab-e-fp16-fp4/job-$job"
New-Item -ItemType Directory -Force $stage | Out-Null
$files = @('manifest.json', 'lab-e-fp16-fp4.json', 'lab-e-fp16-fp4.md', 'slurm.json', 'run-request.json', 'quantization.stdout.json', 'training-tests.log', 'full-tests.log', 'checksums.sha256')
foreach ($name in $files) {
    scp "hku-gpu2:$remote/$name" (Join-Path $stage $name)
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $name" }
}
scp "hku-gpu2:/userhome/cs2/u3665453/AgentLadder/logs/lab-e-$job.log" (Join-Path $stage 'slurm.log')
if ($LASTEXITCODE -ne 0) { throw 'Log download failed' }
$expected = @{}
foreach ($line in Get-Content (Join-Path $stage 'checksums.sha256')) {
    if ($line -match '^([0-9a-f]{64})\s+(.+)$') { $expected[$Matches[2].Trim()] = $Matches[1] }
}
foreach ($name in $files | Where-Object { $_ -ne 'checksums.sha256' }) {
    $actual = (Get-FileHash (Join-Path $stage $name) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected[$name] -ne $actual) { throw "Hash mismatch: $name" }
}
$report = Get-Content -Raw (Join-Path $stage 'lab-e-fp16-fp4.json') | ConvertFrom-Json
if (-not $report.passed -or @($report.checks.PSObject.Properties | Where-Object { -not $_.Value }).Count) { throw 'Lab E report failed' }
ssh -o BatchMode=yes hku-gpu2 "squeue -u u3665453 -o '%i|%P|%j|%T|%M|%l|%R'; ps -u u3665453 -o pid,etime,cmd | grep -E 'python|torchrun|accelerate|srun' | grep -v grep || true"
if ($LASTEXITCODE -ne 0) { throw 'Final process check failed' }
[ordered]@{
    job_id = $job
    local_stage = $stage
    report_passed = $true
    fp16_checkpoint = "$remote/tiny_fp16_amp.pt"
    w4a16_checkpoint = "$remote/tiny_w4a16.pt"
    checkpoints_downloaded = $false
} | ConvertTo-Json
