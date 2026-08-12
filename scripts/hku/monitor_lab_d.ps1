param([string]$Submission = ".tmp/hku/lab-d-submission.json")
$ErrorActionPreference="Stop";$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path;$r=Get-Content -Raw (Resolve-Path (Join-Path $root $Submission))|ConvertFrom-Json;$job=[string]$r.job_id
if($job -notmatch '^[0-9]+$'){throw 'Invalid Job ID'};$log="/userhome/cs2/u3665453/AgentLadder/logs/lab-d-$job.log";if([string]$r.remote_log -ne $log){throw 'Unexpected log path'}
ssh -o BatchMode=yes -o ConnectTimeout=15 hku-gpu2 "squeue -j '$job' -o '%i|%P|%j|%T|%M|%l|%R'; tail -n 160 '$log' 2>/dev/null || true";if($LASTEXITCODE -ne 0){throw 'Monitor failed'}
