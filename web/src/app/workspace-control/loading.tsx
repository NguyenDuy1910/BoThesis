import { ProductLoadingSkeleton } from "@/components/ui/ProductLoadingSkeleton";

/** The dynamic route has no resolved section yet, so do not imply one. */
export default function ControlPlaneLoading() {
  return <ProductLoadingSkeleton />;
}
