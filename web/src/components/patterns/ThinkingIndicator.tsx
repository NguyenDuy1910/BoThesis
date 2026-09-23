/**
 * The LLM pending treatment.
 *
 * Activity stays text-only so the assistant mark remains the sole icon in the
 * identity block. `label` names current work in plain language.
 */
export function ThinkingIndicator({ label }: { label?: string }) {
  return (
    <p aria-live="polite" aria-busy="true" className="bothesis-agent-thinking" role="status">
      {label && <span className="bothesis-agent-thinking__label" key={label}>{label}</span>}
    </p>
  );
}
