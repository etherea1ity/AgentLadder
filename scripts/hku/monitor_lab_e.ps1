param([string]$Submission = ".tmp/hku/lab-e-submission.json")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$record = Get-Content -Raw (Resolve-Path (Join-Path $root $Submission)) | ConvertFrom-Json
$job = [string]$record.job_id
if ($job -notmatch '^[0-9]+$') { throw 'Invalid Job ID' }
$log = "/userhome/cs2/u3665453/AgentLadder/logs/lab-e-$job.log"
if ([string]$record.remote_log -ne $log) { throw 'Unexpected log path' }
ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -j '$job' -o '%i|%P|%j|%T|%M|%l|%R'; scontrol show job '$job' -o 2>/dev/null || true; tail -n 180 '$log' 2>/dev/null || true"
if ($LASTEXITCODE -ne 0) { throw 'Monitor failed' }
