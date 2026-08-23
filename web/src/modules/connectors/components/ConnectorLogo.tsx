import { Cloud, FileUp } from "lucide-react";

import { cn } from "@/lib/cn";
import { connectorDefinition, type ConnectorProvider } from "../catalog";

export function ConnectorLogo({
  provider,
  size = "md",
}: {
  provider: ConnectorProvider | string;
  size?: "sm" | "md" | "lg";
}) {
  const definition = connectorDefinition(provider);
  const dimensions = size === "lg" ? "h-13 w-13 rounded-[0.9rem]" : size === "md" ? "h-10 w-10 rounded-xl" : "h-8 w-8 rounded-lg";
  const iconDimensions = size === "lg" ? "h-7 w-7" : size === "md" ? "h-5 w-5" : "h-4 w-4";
  const outer = cn(
    "inline-flex shrink-0 items-center justify-center border border-black/[0.055] bg-white shadow-[0_1px_2px_rgb(15_23_42/0.06)]",
    dimensions,
  );

  if (provider === "confluence") return <span aria-hidden="true" className={outer} style={{ color: "#1868DB" }}><svg className={iconDimensions} fill="currentColor" viewBox="0 0 24 24"><path d="M.87 18.257c-.248.382-.53.875-.763 1.245a.764.764 0 0 0 .255 1.04l4.965 3.054a.764.764 0 0 0 1.058-.26c.199-.332.454-.763.733-1.221 1.967-3.247 3.945-2.853 7.508-1.146l4.957 2.337a.764.764 0 0 0 1.028-.382l2.364-5.346a.764.764 0 0 0-.382-1c-1.86-.876-3.52-1.674-4.965-2.361C10.911 10.97 5.224 11.185.87 18.257zM23.131 5.743c.249-.405.531-.875.764-1.25a.764.764 0 0 0-.256-1.034L18.675.404a.764.764 0 0 0-1.058.26c-.195.335-.451.763-.734 1.225-1.966 3.246-1.966 2.85-7.508 1.146L4.437.694a.764.764 0 0 0-1.027.382L1.046 6.422a.764.764 0 0 0 .382 1c1.039.49 3.105 1.467 4.965 2.361 6.698 3.246 12.392 3.029 16.738-4.04z" /></svg></span>;
  if (provider === "google_drive") return <span aria-hidden="true" className={outer}><svg className={iconDimensions} viewBox="0 0 24 24"><path d="M8.3 2.5h7.4l7.2 12.4h-7.4z" fill="#FFC107"/><path d="M8.3 2.5 1.1 14.9l3.7 6.4L12 8.9z" fill="#34A853"/><path d="M4.8 21.3h14.4l3.7-6.4H8.5z" fill="#4285F4"/></svg></span>;
  if (provider === "jira") return <span aria-hidden="true" className={outer} style={{ color: "#2684FF" }}><svg className={iconDimensions} fill="currentColor" viewBox="0 0 24 24"><path d="M11.571 11.513H0a5.218 5.218 0 0 0 5.232 5.215h2.13v2.057A5.215 5.215 0 0 0 12.575 24V12.518a1.005 1.005 0 0 0-1.005-1.005zm5.723-5.756H5.736a5.215 5.215 0 0 0 5.215 5.214h2.129v2.058a5.218 5.218 0 0 0 5.215 5.214V6.758a1.001 1.001 0 0 0-1.001-1.001zM23.013 0H11.455a5.215 5.215 0 0 0 5.215 5.215h2.129v2.057A5.215 5.215 0 0 0 24 12.483V1.005A1.001 1.001 0 0 0 23.013 0Z" /></svg></span>;
  if (provider === "notion") return <span aria-hidden="true" className={cn(outer, "font-serif text-lg font-bold text-black")}>N</span>;
  if (provider === "slack") return <span aria-hidden="true" className={outer}><svg className={iconDimensions} fill="none" viewBox="0 0 24 24"><path d="M6.3 13.7a2.1 2.1 0 1 1-2.1-2.1h2.1v2.1Zm1.05 0a2.1 2.1 0 1 1 4.2 0v5.25a2.1 2.1 0 1 1-4.2 0V13.7Z" fill="#36C5F0"/><path d="M10.3 6.3a2.1 2.1 0 1 1 2.1-2.1v2.1h-2.1Zm0 1.05a2.1 2.1 0 1 1 0 4.2H5.05a2.1 2.1 0 1 1 0-4.2h5.25Z" fill="#2EB67D"/><path d="M17.7 10.3a2.1 2.1 0 1 1 2.1 2.1h-2.1v-2.1Zm-1.05 0a2.1 2.1 0 1 1-4.2 0V5.05a2.1 2.1 0 1 1 4.2 0v5.25Z" fill="#ECB22E"/><path d="M13.7 17.7a2.1 2.1 0 1 1-2.1 2.1v-2.1h2.1Zm0-1.05a2.1 2.1 0 1 1 0-4.2h5.25a2.1 2.1 0 1 1 0 4.2H13.7Z" fill="#E01E5A"/></svg></span>;

  const Icon = definition?.icon ?? (provider === "file" ? FileUp : Cloud);
  return (
    <span aria-hidden="true" className={outer} style={{ color: definition?.color ?? "#64748B" }}>
      <Icon className={iconDimensions} strokeWidth={1.8} />
    </span>
  );
}
