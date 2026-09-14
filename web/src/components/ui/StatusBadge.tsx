import { Badge, type BadgeTone } from "@/components/ui/Badge";

interface StatusPresentation {
  label: string;
  tone: BadgeTone;
  /** True while the backend is still working on this record. */
  moving?: boolean;
}

/**
 * The single place a backend status string becomes something an administrator
 * reads. Adding a status to the backend without adding it here shows the raw
 * value in title case rather than inventing a colour for it.
 */
const statuses: Record<string, StatusPresentation> = {
  // Lifecycle shared by users, groups, roles, policies, connections, sources.
  active: { label: "Active", tone: "success" },
  inactive: { label: "Inactive", tone: "neutral" },
  disabled: { label: "Disabled", tone: "neutral" },
  draft: { label: "Draft", tone: "neutral" },
  paused: { label: "Paused", tone: "neutral" },
  archived: { label: "Archived", tone: "neutral" },
  error: { label: "Error", tone: "danger" },

  // Content processing.
  pending: { label: "Queued", tone: "info", moving: true },
  processing: { label: "Processing", tone: "info", moving: true },
  indexing: { label: "Indexing", tone: "info", moving: true },
  ready: { label: "Ready", tone: "success" },
  unsupported: { label: "Unsupported file", tone: "warning" },

  // Runs.
  running: { label: "Running", tone: "info", moving: true },
  syncing: { label: "Syncing", tone: "info", moving: true },
  completed: { label: "Completed", tone: "success" },
  succeeded: { label: "Succeeded", tone: "success" },
  success: { label: "Success", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  failure: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  terminated: { label: "Terminated", tone: "neutral" },
  timed_out: { label: "Timed out", tone: "warning" },

  // Access requests.
  approved: { label: "Approved", tone: "success" },
  denied: { label: "Denied", tone: "danger" },

  // Connectivity.
  connected: { label: "Connected", tone: "success" },
  available: { label: "Available", tone: "neutral" },
  unknown: { label: "Unknown", tone: "neutral" },
};

/**
 * A domain's own reading of a status string.
 *
 * The dictionary above is the product-wide vocabulary, and one backend word
 * can mean different things in different places: `pending` is "Queued" for a
 * document waiting to be indexed, but "Review" for a workspace waiting on an
 * administrator. A domain passes its own entries rather than forking the
 * component or inventing a second badge.
 */
export type StatusVocabulary = Record<string, StatusPresentation>;

export function statusPresentation(
  status?: string | null,
  vocabulary?: StatusVocabulary,
): StatusPresentation {
  const key = String(status ?? "").toLowerCase().trim();
  return (
    vocabulary?.[key] ??
    statuses[key] ?? {
      label: key
        ? key.replaceAll(/[._-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
        : "Unknown",
      tone: "neutral",
    }
  );
}

export function StatusBadge({
  status,
  label,
  className,
  vocabulary,
}: {
  status?: string | null;
  /** Overrides the derived label while keeping the derived colour. */
  label?: string;
  className?: string;
  /** This domain's reading of the status, checked before the shared one. */
  vocabulary?: StatusVocabulary;
}) {
  const presentation = statusPresentation(status, vocabulary);
  return (
    <Badge className={className} dot pulse={presentation.moving} tone={presentation.tone}>
      {label ?? presentation.label}
    </Badge>
  );
}

/**
 * A document is only useful once it can be retrieved, so its two backend
 * fields (`status` and `indexed`) collapse into one thing the admin cares
 * about: can the assistant answer from this yet?
 */
export function DocumentStatusBadge({
  status,
  indexed,
}: {
  status?: string | null;
  indexed?: boolean;
}) {
  const key = String(status ?? "").toLowerCase();
  if (key === "ready") {
    return indexed ? (
      <Badge dot tone="success">
        Searchable
      </Badge>
    ) : (
      <Badge dot tone="neutral">
        Stored, not indexed
      </Badge>
    );
  }
  return <StatusBadge status={status} />;
}
