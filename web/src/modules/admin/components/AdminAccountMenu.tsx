"use client";

import {
  Check,
  ChevronsUpDown,
  MessageSquareText,
  Monitor,
  Moon,
  Settings,
  Sun,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { Avatar } from "@/components/ui/Avatar";
import {
  Dropdown,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
} from "@/components/ui/Dropdown";
import { useTheme, type ThemeMode } from "@/modules/chat/hooks/useTheme";
import { useAdminWorkspace, viewerName } from "@/modules/admin/workspace";

const themeOptions: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match system", icon: Monitor },
];

/**
 * The account control lives at the foot of the navigation, where products of
 * this shape put it, and carries the few settings that belong to the person
 * rather than to the workspace.
 */
export function AdminAccountMenu({ compact }: { compact: boolean }) {
  const router = useRouter();
  const { viewer } = useAdminWorkspace();
  const { theme, setTheme } = useTheme();
  const name = viewerName(viewer);
  const role = viewer?.membership?.role?.display_name;

  return (
    <Dropdown
      align="left"
      ariaLabel="Account and preferences"
      buttonClassName={
        compact
          ? "h-9 w-9 justify-center bg-transparent px-0 shadow-none hover:bg-[var(--adm-row-hover)] hover:shadow-none"
          : "h-11 w-full justify-start gap-2.5 bg-transparent px-1.5 shadow-none hover:bg-[var(--adm-row-hover)] hover:shadow-none"
      }
      className="w-full"
      label={
        <>
          <Avatar name={name} size={compact ? "md" : "lg"} />
          {!compact && (
            <span className="grid min-w-0 flex-1 text-left leading-tight">
              <span className="truncate text-[0.8125rem] font-semibold text-[var(--text)]">
                {name}
              </span>
              {role && (
                <span className="truncate text-[0.6875rem] font-normal text-[var(--text-muted)]">
                  {role}
                </span>
              )}
            </span>
          )}
          {!compact && (
            <ChevronsUpDown
              aria-hidden="true"
              className="h-3.5 w-3.5 shrink-0 text-[var(--text-muted)]"
            />
          )}
        </>
      }
      menuClassName="min-w-60"
      showChevron={false}
    >
      {!compact && (
        <>
          <div className="px-2.5 py-2">
            <p className="truncate text-[0.8125rem] font-semibold text-[var(--text)]">
              {name}
            </p>
            {viewer?.email && (
              <p className="truncate text-[0.75rem] text-[var(--text-muted)]">
                {viewer.email}
              </p>
            )}
          </div>
          <DropdownSeparator />
        </>
      )}

      <DropdownLabel>Appearance</DropdownLabel>
      {themeOptions.map((option) => {
        const Icon = option.icon;
        return (
          <DropdownItem
            key={option.value}
            onClick={() => setTheme(option.value)}
            selected={theme === option.value}
          >
            <Icon aria-hidden="true" className="h-4 w-4" />
            <span className="flex-1">{option.label}</span>
            {theme === option.value && (
              <Check aria-hidden="true" className="h-3.5 w-3.5" />
            )}
          </DropdownItem>
        );
      })}

      <DropdownSeparator />
      <DropdownItem onClick={() => router.push("/admin/settings")}>
        <Settings aria-hidden="true" className="h-4 w-4" />
        Workspace settings
      </DropdownItem>
      <DropdownItem onClick={() => router.push("/app")}>
        <MessageSquareText aria-hidden="true" className="h-4 w-4" />
        Open knowledge workspace
      </DropdownItem>
    </Dropdown>
  );
}

