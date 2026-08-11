import { ToastProvider } from "@/components/ui/Toast";

export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <ToastProvider>{children}</ToastProvider>;
}
