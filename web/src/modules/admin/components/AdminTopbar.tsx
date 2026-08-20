"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { ChevronRight, ShieldCheck } from "lucide-react";
import { MobileMenuButton } from "./AdminSidebar";

interface AdminTopbarProps {
  onMobileMenuOpen: () => void;
}

export function AdminTopbar({ onMobileMenuOpen }: AdminTopbarProps) {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean).slice(1);
  const breadcrumbs = segments.map((segment, idx) => {
    const href = "/admin/" + segments.slice(0, idx + 1).join("/");
    const label = segment
      .replace(/[-_]/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
    return { href, label };
  });

  return (
    <div className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur lg:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <MobileMenuButton onClick={onMobileMenuOpen} />
        <nav className="flex min-w-0 items-center gap-1 text-xs">
          <Link href="/admin/overview" className="shrink-0 text-slate-500 transition hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20">
            Admin
          </Link>
          {breadcrumbs.map((crumb, idx) => (
            <span key={crumb.href} className="flex min-w-0 items-center gap-1">
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-300" />
              {idx === breadcrumbs.length - 1 ? (
                <span className="truncate font-medium text-slate-700">{crumb.label}</span>
              ) : (
                <Link href={crumb.href} className="truncate text-slate-500 transition hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20">
                  {crumb.label}
                </Link>
              )}
            </span>
          ))}
        </nav>
      </div>
      <div className="hidden shrink-0 items-center gap-1.5 rounded-md bg-teal-50 px-2 py-1 text-xs font-medium text-teal-800 ring-1 ring-inset ring-teal-100 sm:inline-flex">
        <ShieldCheck className="h-3.5 w-3.5" />
        Admin Dashboard
      </div>
    </div>
  );
}
