"use client";

import { NotBackedYet } from "@/components/ui/NotBackedYet";

export function PlatformModelsPage() {
  return (
    <NotBackedYet
      description="Which models and capabilities each workspace may use will be governed here. No endpoint stores that policy yet; the models a deployment can reach are currently fixed by its environment configuration."
      title="Model availability is not stored yet"
    />
  );
}
