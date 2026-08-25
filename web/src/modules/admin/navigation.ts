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
    label: "Workspace",
    items: [
      { label: "Overview", href: "/admin/overview", icon: LayoutDashboard },
    ],
  },
  {
    label: "Knowledge",
    items: [
      { label: "Knowledge Bases", href: "/admin/knowledge-bases", icon: Library },
      { label: "Documents", href: "/admin/documents", icon: FileText },
    ],
  },
  {
    label: "Connectors",
    items: [
      { label: "Sources & Integrations", href: "/admin/sources", icon: Plug },
      { label: "Sync Activity", href: "/admin/sync-activity", icon: RefreshCw },
    ],
  },
  {
    label: "Automations",
    items: [
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
