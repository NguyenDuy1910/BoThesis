import { AdminShell } from "@/modules/admin/components/AdminShell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminShell>{children}</AdminShell>;
}
