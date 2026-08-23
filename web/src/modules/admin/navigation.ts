import {
  LayoutDashboard,
  Plug,
  Database,
  FileText,
  Layers,
  Users,
  UsersRound,
  ShieldCheck,
  Lock,
  ScrollText,
  KeyRound,
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
    label: "Data",
    items: [
      { label: "Connectors", href: "/admin/connectors", icon: Plug },
      { label: "Ingestion", href: "/admin/ingestion/jobs", icon: Database },
      { label: "Items", href: "/admin/items", icon: FileText },
    ],
  },
  {
    label: "Organization",
    items: [
      { label: "Spaces", href: "/admin/spaces", icon: Layers },
      { label: "Users", href: "/admin/users", icon: Users },
      { label: "Groups", href: "/admin/groups", icon: UsersRound },
      { label: "Access Requests", href: "/admin/access-requests", icon: KeyRound },
      { label: "Roles", href: "/admin/roles", icon: ShieldCheck },
      { label: "ACL Policies", href: "/admin/acl", icon: Lock },
    ],
  },
  {
    label: "System",
    items: [
      { label: "Audit Logs", href: "/admin/audit-logs", icon: ScrollText },
    ],
  },
];
