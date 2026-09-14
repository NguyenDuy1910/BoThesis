"use client";

import Link from "next/link";
import { Check, Compass } from "lucide-react";
import { useState } from "react";
import { WorkspaceMark } from "@/components/patterns";
import { Dialog } from "@/components/ui/Dialog";
import { SearchInput } from "@/components/ui/SearchInput";
import { EmptyState } from "@/components/ui/EmptyState";
import type { AuthTenant } from "@/lib/auth/session";
import { useAuthSession } from "@/lib/hooks/useAuthSession";

export function WorkspaceSwitcherDialog({ error, onClose, onSelect, open, switchingId, workspaces }: {
  error: string | null; onClose: () => void; onSelect: (id: string) => void;
  open: boolean; switchingId: string | null; workspaces: AuthTenant[];
}) {
  const session = useAuthSession();
  const [search, setSearch] = useState("");
  const matches = workspaces.filter((workspace) => workspace.name.toLowerCase().includes(search.toLowerCase()));
  const groups = [
    { label: "Current", rows: matches.filter((item) => item.id === session?.active_tenant_id) },
    { label: "Your organizations", rows: matches.filter((item) => item.id !== session?.active_tenant_id && item.role_code !== "visitor") },
    { label: "Available to you", rows: matches.filter((item) => item.id !== session?.active_tenant_id && item.role_code === "visitor") },
  ];
  return (
    <Dialog className="max-w-sm" onClose={onClose} open={open} title="Switch workspace">
      <SearchInput ariaLabel="Search workspaces" onChange={setSearch} placeholder="Search workspaces…" value={search} />
      <div className="max-h-[55vh] overflow-y-auto py-3">
        {groups.map((group) => group.rows.length > 0 && <section key={group.label} aria-label={group.label}>
          <h3 className="px-2 pb-1 pt-3 text-[length:var(--text-size-caption)] uppercase tracking-wide text-[var(--text-tertiary)]">{group.label}</h3>
          {group.rows.map((item) => <button key={item.id} className="flex min-h-14 w-full items-center gap-3 rounded-[var(--radius-sm)] p-2 text-left hover:bg-[var(--surface-hover)]" disabled={Boolean(switchingId)} onClick={() => item.id === session?.active_tenant_id ? onClose() : onSelect(item.id)} type="button">
            <WorkspaceMark name={item.name} size="md" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{item.name}</span><span className="block text-xs text-[var(--text-tertiary)]">{switchingId === item.id ? "Switching…" : item.role_code === "visitor" ? "Available to everyone" : "Organization member"}</span></span>{item.id === session?.active_tenant_id && <Check aria-label="Current workspace" size={16} />}
          </button>)}
        </section>)}
        {!matches.length && <EmptyState title="No workspaces found" description="Try a different name." />}
      </div>
      {error && <p role="alert" className="text-sm text-[var(--status-danger-text)]">{error}</p>}
      <Link className="flex items-center gap-2 border-t border-[var(--border-subtle)] pt-3 text-sm" href="/workspaces" onClick={onClose}><Compass size={16} aria-hidden="true" />Explore workspaces</Link>
    </Dialog>
  );
}
