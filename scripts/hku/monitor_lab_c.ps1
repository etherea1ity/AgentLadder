param([string]$Submission = ".tmp/hku/lab-c-submission.json")
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$record = Get-Content -Raw (Resolve-Path (Join-Path $root $Submission)) | ConvertFrom-Json
$jobId = [string]$record.job_id
if ($jobId -notmatch "^[0-9]+$") { throw "Invalid Lab C Job ID" }
$expectedLog = "/userhome/cs2/u3665453/AgentLadder/logs/lab-c-$jobId.log"
if ([string]$record.remote_log -ne $expectedLog) { throw "Unexpected Lab C log path" }
ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -j '$jobId' -o '%i|%P|%j|%T|%M|%l|%R'; tail -n 140 '$expectedLog' 2>/dev/null || true"
if ($LASTEXITCODE -ne 0) { throw "Could not monitor Lab C" }
