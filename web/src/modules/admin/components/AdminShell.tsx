"use client";

import { useState } from "react";
import { AppShell } from "@/components/ui/AppShell";
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
      <AppShell
        sidebar={<AdminSidebar
          collapsed={collapsed}
          onToggle={() => setCollapsed(!collapsed)}
          mobileOpen={mobileOpen}
          onMobileClose={() => setMobileOpen(false)}
        />}
        variant="admin"
      >
        <div className="admin-shell__workspace">
          <AdminTopbar onMobileMenuOpen={() => setMobileOpen(true)} />
          <main className="admin-shell__main" id="main-content">
            {children}
          </main>
        </div>
      </AppShell>
    </ToastProvider>
  );
}
