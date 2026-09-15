"use client";

import { ExternalLink, LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/Button";

/**
 * What the page says while a consent window is open somewhere else.
 *
 * A popup that slipped behind the main window is the most common way this
 * flow appears to hang: nothing is broken, the reader simply cannot see the
 * thing waiting for them. So the state is named, and the one action that
 * resolves it — bring that window back — is offered before anything else.
 */
export function AuthorizationWaiting({
  providerName,
  onFocus,
  onCancel,
}: {
  providerName: string;
  onFocus: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="knowledge-waiting" role="status">
      <LoaderCircle
        aria-hidden="true"
        className="knowledge-waiting__spinner motion-safe:animate-spin"
        size={22}
      />
      <strong>Finish signing in to {providerName}</strong>
      <p>
        A separate window is open for that. {providerName} decides what BoThesis
        may read — nothing is connected here until it says so.
      </p>
      <div className="knowledge-waiting__actions">
        <Button icon={<ExternalLink size={15} />} onClick={onFocus} size="sm" variant="secondary">
          Show that window
        </Button>
        <Button onClick={onCancel} size="sm" variant="ghost">
          Cancel
        </Button>
      </div>
    </div>
  );
}
