"use client";

import { ChevronDown, MoreHorizontal } from "lucide-react";

import { WorkspaceMark } from "@/components/patterns";
import { Avatar } from "@/components/ui/Avatar";
import { cn } from "@/lib/cn";

type WorkspaceDock = {
  variant: "workspace";
  workspaceName: string;
  userName: string;
  collapsed: boolean;
  open: boolean;
};

type PlatformDock = {
  variant: "platform";
  platformContext: string;
  userName: string;
  collapsed: boolean;
  open: boolean;
};

/**
 * The label inside the single identity/context trigger at the bottom of a
 * rail. Menus own their allowed actions; this component only preserves the
 * common density, hierarchy and collapsed treatment across the two contexts.
 */
export function IdentityContextDock(props: WorkspaceDock | PlatformDock) {
  if (props.collapsed) {
    return props.variant === "workspace" ? (
      <WorkspaceMark className="rounded-[6px]" name={props.workspaceName} size="sm" />
    ) : (
      <Avatar name={props.userName} size="rail" />
    );
  }

  if (props.variant === "workspace") {
    return (
      <span className="flex min-w-0 flex-1 items-center gap-2">
        <WorkspaceMark className="rounded-[6px]" name={props.workspaceName} size="sm" />
        <span className="grid min-w-0 flex-1 text-left leading-tight">
          <span className="truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
            {props.workspaceName}
          </span>
          <span className="truncate text-[length:var(--text-size-meta)] font-normal leading-[var(--text-lh-meta)] text-[var(--text-tertiary)]">
            {props.userName}
          </span>
        </span>
        <ChevronDown
          aria-hidden="true"
          className={cn(
            "h-5 w-5 shrink-0 text-[var(--text-tertiary)]",
            "transition-transform duration-[var(--duration-fast)] ease-[var(--ease-out)]",
            props.open && "rotate-180",
          )}
        />
      </span>
    );
  }

  return (
    <span className="flex min-w-0 flex-1 items-center gap-2.5">
      <Avatar name={props.userName} size="rail" />
      <span className="grid min-w-0 flex-1 text-left leading-tight">
        <span className="truncate text-[length:var(--text-size-nav)] font-medium leading-[var(--text-lh-nav)] text-[var(--text-primary)]">
          {props.userName}
        </span>
        <span className="truncate text-[length:var(--text-size-caption)] font-normal leading-[var(--text-lh-caption)] text-[var(--text-tertiary)]">
          {props.platformContext}
        </span>
      </span>
      <MoreHorizontal aria-hidden="true" className="h-5 w-5 shrink-0 text-[var(--text-tertiary)]" />
    </span>
  );
}
