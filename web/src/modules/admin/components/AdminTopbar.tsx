"use client";

import { ChevronRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { MobileMenuButton } from "./AdminSidebar";

interface AdminTopbarProps {
  onMobileMenuOpen: () => void;
}

export function AdminTopbar({ onMobileMenuOpen }: AdminTopbarProps) {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean).slice(1);
  const breadcrumbs = segments.map((segment, index) => ({
    href: "/admin/" + segments.slice(0, index + 1).join("/"),
    label: breadcrumbLabels[segment] ?? segment.replace(/[-_]/g, " ").replace(/\b\w/g, (character) => character.toUpperCase()),
  }));

  return (
    <header className="admin-topbar">
      <div className="admin-topbar__left">
        <MobileMenuButton onClick={onMobileMenuOpen} />
        <nav aria-label="Breadcrumb" className="admin-topbar__breadcrumbs">
          <Link href="/admin/overview">Admin</Link>
          {breadcrumbs.map((crumb, index) => (
            <span key={crumb.href}>
              <ChevronRight aria-hidden="true" size={13} />
              {index === breadcrumbs.length - 1 ? (
                <span aria-current="page">{crumb.label}</span>
              ) : (
                <Link href={crumb.href}>{crumb.label}</Link>
              )}
            </span>
          ))}
        </nav>
      </div>
      <div className="admin-topbar__status" role="status">
        <ShieldCheck aria-hidden="true" size={14} />
        Server enforced
      </div>
    </header>
  );
}

const breadcrumbLabels: Record<string, string> = {
  acl: "ACL Policies",
  connectors: "Data Sources",
  "access-requests": "Access Requests",
  "audit-logs": "Audit Logs",
};
