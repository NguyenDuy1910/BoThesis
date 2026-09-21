import { ProductShell } from "@/components/shell/ProductShell";

/**
 * A route group keeps the public URLs unchanged while giving all user-product
 * destinations one persistent client shell.
 */
export default function ProductLayout({ children }: { children: React.ReactNode }) {
  return <ProductShell>{children}</ProductShell>;
}
