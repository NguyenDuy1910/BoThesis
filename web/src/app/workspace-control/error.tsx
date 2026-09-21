"use client";

import { AlertTriangle } from "lucide-react";

export default function WorkspaceControlRouteError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <section className="shell__route-boundary" role="alert">
      <AlertTriangle aria-hidden="true" size={20} />
      <strong>Could not open this workspace control view</strong>
      <span>Your navigation and workspace controls are still available.</span>
      <button onClick={reset} type="button">Try again</button>
    </section>
  );
}
