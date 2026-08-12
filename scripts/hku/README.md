# HKU GPU Farm Execution Boundary

This directory is an agent-facing execution surface for the AgentLadder
algorithm labs. The authoritative access and safety contract is the user's
local `C:\Users\jsj31\Desktop\HKU_GPU_FARM_HANDOFF.md`.

Rules:

- Use the existing `hku-gpu2` SSH alias and public-key authentication. Never
  copy passwords, private keys, `.env` files, or API keys.
- Inspect VPN reachability, the Slurm queue, quota, and remote targets before
  writing anything.
- Never train on `gpu2gate1`; it is only a login gateway.
- Deploy each source bundle into a new directory below
  `/userhome/cs2/u3665453/AgentLadder/deployments/`. Do not overwrite an
  unknown remote tree.
- Use the absolute isolated Python path. The project requires Python 3.11; do
  not silently run it with the gateway's Python 3.10.
- Submit training and evaluation through `sbatch`, record the returned job ID,
  and poll no more frequently than every 30-60 seconds.
- Store checkpoints, reports, logs, and hashes below the remote AgentLadder
  artifact root. Download only staged report/checksum files unless a checkpoint
  is explicitly needed locally.
- After every job, verify `squeue` contains only its header and check for
  leftover Python, torchrun, accelerate, or srun processes. Do not disconnect
  or reconfigure the user's VPN.

Gate 2 remote sequence:

1. Build a secret-free source archive locally and record its SHA-256.
2. Inspect the remote root; upload the archive to a new incoming path.
3. Extract it into a new hash-named deployment directory.
4. Run `bootstrap_agentladder.sh` on the gateway only for environment setup and
   import validation.
5. Submit `lab_b_tiny_pretrain.sbatch` with `AGENTLADDER_SOURCE_DIR` exported.
6. Monitor the exact job ID and its log.
7. Verify the report, manifest, checkpoint, and `checksums.sha256` on the
   compute node result.
8. Stage-download textual evidence, compare local and remote SHA-256 values,
   and perform any required CPU sanity check as a separate cloud job.
9. Confirm that no `RUNNING` or `PENDING` job remains.

The local archive command is:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/hku/package_agentladder.ps1
```

The returned archive hash, the full parent commit, and the deployment directory
must be exported with `sbatch --export`; the batch script refuses placeholders.

After the existing VPN is reachable, the guarded deploy/submit command is:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/hku/submit_lab_b.ps1
```

It refuses unexpected SSH identity, existing hash-named targets, malformed
hashes, archive drift, upload hash mismatch, bootstrap failure, and an invalid
Slurm Job ID.

Monitoring and report retrieval use the exact recorded Job ID:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/hku/monitor_lab_b.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/fetch_lab_b_reports.ps1
```

The fetch command leaves `tiny_dense.pt` in the hash-verified remote artifact
directory. It stages only reports, manifests, logs, and checksums locally; the
formal checkpoint and all metric computation remain on HKU infrastructure.
