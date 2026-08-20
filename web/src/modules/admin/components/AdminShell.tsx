"use client";

import { useState } from "react";
import { AdminSidebar } from "./AdminSidebar";
import { AdminTopbar } from "./AdminTopbar";
import { ToastProvider } from "@/components/ui/Toast";

interface AdminShellProps {
  children: React.ReactNode;
}

export function AdminShell({ children }: AdminShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <ToastProvider>
      <div className="flex h-dvh w-screen overflow-hidden bg-slate-50 text-slate-900">
        <AdminSidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          mobileOpen={mobileOpen}
          onMobileClose={() => setMobileOpen(false)}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-slate-50">
          <AdminTopbar onMobileMenuOpen={() => setMobileOpen(true)} />
          <main className="min-h-0 flex-1 overflow-y-auto px-4 py-4 lg:px-6">
            {children}
          </main>
        </div>
      </div>
    </ToastProvider>
  );
}
