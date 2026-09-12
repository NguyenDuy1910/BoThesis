import { Bot } from "lucide-react";
import Link from "next/link";

/** A persistent route back to the product's conversational assistant. */
export function GlobalAssistantLauncher() {
  return (
    <Link
      aria-label="Ask Enterprise Agent"
      className="global-assistant-launcher"
      href="/app"
      title="Ask Enterprise Agent"
    >
      <Bot aria-hidden="true" className="h-5 w-5" />
      <span aria-hidden="true" />
    </Link>
  );
}
