export function KlaraStamp({ label = 'Klara' }: { label?: string }) {
  return <span className="klara-stamp" aria-hidden="true"><img src="/brand/klara/klara-mark-light.png" alt="" /><span>{label}</span></span>;
}
