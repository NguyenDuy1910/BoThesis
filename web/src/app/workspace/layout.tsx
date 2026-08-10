import { ToastProvider } from "@/components/ui/Toast";

export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ToastProvider>{children}</ToastProvider>;
}
