# Chapter 16 Subagents, Teams, and Worktrees Gate

Language: [Chinese](./ch16-subagents-team-worktree.md) | English

Status: **PASS**

- Scorer: `klara.chapter16-teams-worktrees.v1`
- Checks: `19/19`
- Critical delegation/isolation rate: `1.000`
- Public secret leaks: `0`

## Acceptance Checks

| Check | Result |
| --- | --- |
| api_exposes_team_mailbox_claim_authority_and_worktrees | PASS |
| autonomous_claim_reuses_durable_lease | PASS |
| bilingual_tutorial_exists | PASS |
| mailbox_has_monotonic_cursor_and_ack | PASS |
| mailbox_owner_isolation_is_opaque | PASS |
| one_shot_projects_one_completed_child_task | PASS |
| one_shot_returns_summary_only_with_hash | PASS |
| one_shot_runs_explicit_packet_without_parent_history | PASS |
| one_shot_spawn_requires_exact_permission | PASS |
| permission_bubbling_uses_existing_attenuation | PASS |
| persistent_teammate_requires_permission | PASS |
| question_answer_consistency_and_no_strange_output | PASS |
| real_git_worktree_is_project_contained | PASS |
| stage_manifest_exists | PASS |
| task_context_is_hashed_and_lease_token_not_persisted | PASS |
| ui_reads_real_team_state_and_actions | PASS |
| ui_shows_authority_mailbox_worktree_and_stop | PASS |
| worktree_create_and_remove_require_permission | PASS |
| worktree_does_not_use_shell_interpolation | PASS |

## Question/Answer Consistency Probe

- Question: 把这个证据检查交给子 Agent，但不要把整段对话或额外权限交出去；完成后只告诉我结论。
- Reference: 先请求精确委派权限，只传显式任务包和白名单能力，在隔离任务中执行，并通过父邮箱返回简洁结论；不得共享隐藏推理。
- Candidate observation: Evidence checked; the cited page supports the bounded claim.
- P0 strange responses: `0`

## Limitations

- The gate proves bounded single-host SQLite orchestration, not a production worker fleet or distributed consensus.
- The deterministic one-shot executor proves isolation plumbing; independent cross-model behavioral comparison remains part of Agent Product Freeze.
- Learned multi-agent routing is deliberately excluded until the frozen runtime has produced comparable trajectory data.
