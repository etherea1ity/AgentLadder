# Product Agent Notes

## Findings
- Klara must separate identity from activity: static brand stamp vs active runtime presence.
- Current UI is safe for chain-of-thought because it only shows public labels and backend run events.
- v0.1 should not pre-seed future RAG/research steps; Live Run must reflect events that happened.

## Recommendation
- Use one Active Klara only for the current non-terminal run or composer waiting state.
- Use Static Klara Stamp for completed/history answers.
- Rename real-time labels toward observable activity: Calling model, Writing answer, Saving trace.

## Risks
- “Thinking” wording can imply private reasoning.
- Hardcoded Run Chain can become misleading if it renders future steps before events exist.

## Acceptance Focus
- Sending does not open run panel automatically.
- Active Klara is singleton.
- Live Run shows public activity only, no raw reasoning.

## Challenges
- Motion must distinguish active vs static without implying hidden thought.
- Runtime should emit real events before UI displays new capability steps.
