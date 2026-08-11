"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { appBrand } from "@/lib/brand";
import { adminNavGroups } from "@/modules/admin/navigation";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { ChevronLeft, Menu, MessageSquareText } from "lucide-react";
import { useState } from "react";

interface AdminSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function AdminSidebar({ collapsed, onToggle, mobileOpen, onMobileClose }: AdminSidebarProps) {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === "/admin/overview") return pathname === "/admin/overview";
    return pathname.startsWith(href);
  };

  const sidebarContent = (
    <div className="flex h-full flex-col bg-white">
      <div className="flex h-14 items-center border-b border-slate-200/80 px-3">
        {!collapsed && (
          <div className="flex min-w-0 items-center gap-2.5">
            <BrandLogo
              alt={appBrand.logo.alt}
              className="h-9 w-9 rounded-lg bg-white p-1 shadow-sm ring-1 ring-inset ring-slate-200"
              imageClassName={appBrand.logo.imageClassName}
              label={appBrand.logo.alt}
              size={32}
              src={appBrand.logo.src}
            />
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold leading-5 text-slate-950">{appBrand.adminName}</span>
              <span className="block truncate text-[11px] font-medium text-slate-500">{appBrand.adminSubtitle}</span>
            </span>
          </div>
        )}
        {collapsed && (
          <BrandLogo
            alt={appBrand.logo.alt}
            className="mx-auto h-9 w-9 rounded-lg bg-white p-1 shadow-sm ring-1 ring-inset ring-slate-200"
            imageClassName={appBrand.logo.imageClassName}
            label={appBrand.logo.alt}
            size={32}
            src={appBrand.logo.src}
          />
        )}
        <button
          onClick={onToggle}
          type="button"
          aria-label={collapsed ? "Expand admin navigation" : "Collapse admin navigation"}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
          className={cn(
            "hidden h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20 lg:flex",
            collapsed ? "mx-auto" : "ml-auto"
          )}
        >
          <ChevronLeft className={cn("h-3.5 w-3.5 transition-transform", collapsed && "rotate-180")} />
        </button>
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {adminNavGroups.map((group, groupIdx) => (
          <div key={groupIdx}>
            {group.label && !collapsed && (
              <p className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-normal text-slate-500">
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => onMobileClose()}
                    className={cn(
                      "group relative flex h-9 items-center gap-2 rounded-md px-2.5 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20",
                      active
                        ? "bg-teal-50 text-slate-950 ring-1 ring-inset ring-teal-100"
                        : "text-slate-600 hover:bg-slate-100 hover:text-slate-950",
                      collapsed && "justify-center px-2"
                    )}
                    title={collapsed ? item.label : undefined}
                  >
                    {active && <span className="absolute left-0 h-4 w-0.5 rounded-r-full bg-teal-600" />}
                    <Icon className={cn("h-4 w-4 shrink-0", active ? "text-teal-700" : "text-slate-500 group-hover:text-slate-700")} />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-slate-200 px-2 py-2">
        <Link
          href="/app"
          aria-label={collapsed ? "Back to workspace" : undefined}
          title={collapsed ? "Back to workspace" : undefined}
          className={cn(
            "flex h-9 items-center gap-2 rounded-md px-2 text-sm font-medium text-slate-600 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20",
            collapsed && "justify-center"
          )}
        >
          <MessageSquareText className="h-3.5 w-3.5" />
          {!collapsed && <span>Back to workspace</span>}
        </Link>
      </div>
    </div>
  );

  return (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 bg-slate-950/35 lg:hidden" onClick={onMobileClose} />
      )}

      <aside
        className={cn(
          "fixed left-0 top-0 z-50 h-full border-r border-slate-200 bg-white shadow-xl shadow-slate-950/5 transition-all duration-200 lg:relative lg:z-auto lg:shadow-none",
          collapsed ? "w-[72px]" : "w-[200px]",
          mobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        {sidebarContent}
      </aside>
    </>
  );
}

export function MobileMenuButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label="Open admin navigation"
      type="button"
      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-slate-600 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500/20 lg:hidden"
    >
      <Menu className="h-4 w-4" />
    </button>
  );
}
