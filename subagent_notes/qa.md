# QA / Acceptance Agent Notes

## Findings
- Frontend tests/build were green before this task.
- Backend tests had one unrelated Klara prompt contract failure around exact wording.
- Reduced-motion coverage was missing.

## Recommendation
- Preserve current chat/markdown/dark-mode behavior.
- Add reduced-motion CSS and singleton active presence rule.
- Run `npm test` and `npm run build` after implementation.

## Risks
- Multiple restored nonterminal runs could create multiple active indicators unless UI chooses one visual active run.
- Large motion assets/dependencies could slow the app.

## Acceptance Focus
- No build blocker.
- No broken chat send/stream/stop/delete.
- No markdown/KaTeX regression.
- No chain-of-thought in Live Run.
