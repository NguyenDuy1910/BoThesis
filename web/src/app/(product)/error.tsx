"use client";

import { AlertTriangle } from "lucide-react";

export default function ProductRouteError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <section className="shell__route-boundary" role="alert">
      <AlertTriangle aria-hidden="true" size={20} />
      <strong>Could not open this workspace view</strong>
      <span>The rest of your workspace is still available.</span>
      <button onClick={reset} type="button">Try again</button>
    </section>
  );
}
