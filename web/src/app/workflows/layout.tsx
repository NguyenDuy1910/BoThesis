import { ToastProvider } from "@/components/ui/Toast";

export default function WorkflowsLayout({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}
