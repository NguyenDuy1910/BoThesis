"use client";

import { Construction } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

interface NotBackedYetProps {
  /** What this screen will show, named the way the person asked for it. */
  title: string;
  /** What it will do once an endpoint serves it. */
  description: string;
}

/**
 * A surface whose API does not exist yet.
 *
 * These screens were built ahead of their endpoints. Rather than render
 * invented rows that look like real workspace data, they say plainly that
 * nothing is stored behind them yet — a person deciding whether a setting
 * took effect is never left guessing.
 */
export function NotBackedYet({ title, description }: NotBackedYetProps) {
  return (
    <div className="adm-card">
      <EmptyState
        description={description}
        icon={<Construction aria-hidden="true" className="h-5 w-5" />}
        title={title}
      />
    </div>
  );
}
