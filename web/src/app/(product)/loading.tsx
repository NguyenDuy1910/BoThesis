import { WorkspaceLoadingSkeleton } from "@/components/ui/WorkspaceLoadingSkeleton";

/** This fallback replaces only the product route outlet, never its shell. */
export default function ProductLoading() {
  return <WorkspaceLoadingSkeleton />;
}
