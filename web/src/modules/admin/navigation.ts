import {
  LayoutDashboard,
  Plug,
  FileText,
  Layers,
  Users,
  UsersRound,
  ShieldCheck,
  Lock,
  ScrollText,
  KeyRound,
  Library,
  RefreshCw,
  Workflow,
  CalendarClock,
} from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
}

export interface NavGroup {
  label: string | null;
  items: NavItem[];
}

export const adminNavGroups: NavGroup[] = [
  {
    label: null,
    items: [
      { label: "Overview", href: "/admin/overview", icon: LayoutDashboard },
    ],
  },
  {
    label: "Knowledge",
    items: [
      { label: "Knowledge Bases", href: "/admin/knowledge-bases", icon: Library },
      { label: "All Items", href: "/admin/all-items", icon: FileText },
    ],
  },
  {
    label: "Data",
    items: [
      { label: "Sources & Integrations", href: "/admin/sources", icon: Plug },
      { label: "Sync Activity", href: "/admin/sync-activity", icon: RefreshCw },
    ],
  },
  {
    label: "Automation",
    items: [
      { label: "Schedules", href: "/admin/schedules", icon: CalendarClock },
      { label: "Workflows", href: "/workflows", icon: Workflow },
    ],
  },
  {
    label: "Administration",
    items: [
      { label: "People", href: "/admin/people", icon: Users },
      { label: "Groups", href: "/admin/groups", icon: UsersRound },
      { label: "Access Requests", href: "/admin/access-requests", icon: KeyRound },
      { label: "Roles", href: "/admin/roles", icon: ShieldCheck },
      { label: "Access Policies", href: "/admin/access-policies", icon: Lock },
      { label: "Workspace Settings", href: "/admin/workspace-settings", icon: Layers },
      { label: "Audit Log", href: "/admin/audit-logs", icon: ScrollText },
    ],
  },
];
