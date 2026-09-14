/** This fallback replaces only the product route outlet, never its shell. */
export default function ProductLoading() {
  return (
    <section aria-busy="true" aria-label="Loading workspace" className="shell__route-boundary" role="status">
      <span aria-hidden="true" className="shell__route-boundary-indicator" />
      Loading workspace…
    </section>
  );
}
