import { ProductLoadingSkeleton } from "@/components/ui/ProductLoadingSkeleton";

/** This fallback replaces only the product route outlet, never its shell. */
export default function ProductLoading() {
  return <ProductLoadingSkeleton />;
}
