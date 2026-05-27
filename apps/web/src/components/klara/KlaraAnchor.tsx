import type { PropsWithChildren } from 'react';

export type KlaraAnchorName = 'homeHero' | 'composerDock' | 'assistantRun' | 'tracePanel';

export function KlaraAnchor({ name, children }: PropsWithChildren<{ name: KlaraAnchorName }>) {
  return <span className="klara-anchor" data-klara-anchor={name}>{children}</span>;
}
