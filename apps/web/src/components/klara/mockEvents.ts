import type { KlaraCapabilityChip, KlaraRunEvent, KlaraRunEventKind } from '../../types/domain';

type Scenario = 'minimal' | 'calculator' | 'rag' | 'web' | 'error' | 'loop';
type Step = [KlaraRunEventKind, string, KlaraCapabilityChip[]?, number?];

const scenarios: Record<Scenario, Step[]> = {
  minimal: [
    ['run.started', 'Received question'], ['ask.created', 'Created AskState'], ['model.call.started', 'Calling model...', ['model']], ['answer.started', 'Writing answer...', ['model']], ['answer.completed', 'AnswerState completed'], ['run.completed', 'Completed', ['model']]
  ],
  calculator: [
    ['run.started', 'Received question'], ['ask.created', 'Created AskState'], ['tool.call.started', 'Calling calculator...', ['tool']], ['tool.call.completed', 'Calculator returned observation', ['tool']], ['observation.created', 'Observation created', ['tool']], ['model.call.started', 'Calling model...', ['model']], ['answer.started', 'Writing answer...', ['model']], ['run.completed', 'Completed', ['model']]
  ],
  rag: [
    ['run.started', 'Received question'], ['ask.created', 'Created AskState'], ['retrieval.started', 'Searching local knowledge...', ['rag']], ['chunk.retrieved', 'Reading retrieved chunks...', ['rag']], ['source.selected', 'Selecting useful source...', ['rag']], ['sourcecard.created', 'Source card created', ['rag']], ['answer.started', 'Grounding answer in sources...', ['model', 'rag']], ['citation.created', 'Adding citations...', ['rag']], ['run.completed', 'Completed', ['model']]
  ],
  web: [
    ['run.started', 'Received question'], ['web.search.started', 'Searching the web...', ['web']], ['web.page.read', 'Reading pages...', ['web']], ['verification.started', 'Cross-checking sources...', ['verify', 'web']], ['answer.started', 'Writing answer...', ['model', 'web']], ['run.completed', 'Completed', ['model']]
  ],
  error: [
    ['run.started', 'Received question'], ['model.call.started', 'Calling model...', ['model']], ['run.error', 'Run failed', ['model']]
  ],
  loop: [
    ['run.started', 'Received question'], ['loop.started', 'Loop 1 · deciding next step...', ['rag'], 1], ['retrieval.started', 'Searching local knowledge...', ['rag'], 1], ['loop.started', 'Loop 2 · checking evidence...', ['rag', 'verify'], 2], ['verification.started', 'Checking evidence...', ['verify'], 2], ['answer.started', 'Writing answer...', ['model'], 2], ['run.completed', 'Completed', ['model']]
  ]
};

export function createMockKlaraEvents(scenario: Scenario, runId = `mock_${scenario}`): KlaraRunEvent[] {
  const base = Date.now();
  return scenarios[scenario].map(([kind, publicLabel, capabilities, iteration], index) => ({
    runId,
    eventId: `${runId}_${index + 1}`,
    seq: index + 1,
    timestamp: new Date(base + index * 700).toISOString(),
    kind,
    status: kind === 'run.error' ? 'failed' : kind === 'run.completed' ? 'completed' : index === 0 ? 'started' : 'progress',
    publicLabel,
    publicDetail: publicLabel,
    concept: conceptForKind(kind),
    iteration,
    capabilities,
    safePayload: iteration ? { iteration } : undefined
  }));
}

export const mockKlaraScenarios: Scenario[] = ['minimal', 'calculator', 'rag', 'web', 'error', 'loop'];

function conceptForKind(kind: KlaraRunEventKind) {
  if (kind.startsWith('model') || kind.startsWith('answer')) return 'LLMClient';
  if (kind.startsWith('retrieval') || kind.startsWith('chunk') || kind.startsWith('source')) return 'Retriever';
  if (kind.startsWith('tool') || kind.startsWith('observation')) return 'Tool';
  if (kind.startsWith('web')) return 'WebSearch';
    if (kind.includes('runlog')) return 'RunLog';
  if (kind.includes('ask')) return 'AskState';
  return 'Run';
}
