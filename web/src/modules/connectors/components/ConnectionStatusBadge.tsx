import { Badge } from "@/components/ui/Badge";
import type { ConnectorRegistryStatus } from "../types";

const statusPresentation = {
  connected: { label: "Connected", variant: "success" },
  available: { label: "Available", variant: "default" },
  disabled: { label: "Disabled", variant: "default" },
  needs_setup: { label: "Needs setup", variant: "warning" },
  unavailable: { label: "Not enabled", variant: "default" },
} as const;

export function ConnectionStatusBadge({ status }: { status: ConnectorRegistryStatus }) {
  const presentation = statusPresentation[status];
  return <Badge dot={status !== "unavailable"} variant={presentation.variant}>{presentation.label}</Badge>;
}
