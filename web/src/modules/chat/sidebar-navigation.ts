import { productNavigationItems, type ProductNavigationItem } from "@/lib/product-navigation";

export type SidebarNavigationItem = ProductNavigationItem;
export type SidebarNavigationItemId = SidebarNavigationItem["id"];
export type SidebarDestination = ProductNavigationItem;

/** Chat keeps its compact visual grouping, but the destinations are shared. */
export const sidebarNavigationItems = productNavigationItems.filter(
  (item) => item.id === "chat" || item.id === "knowledge",
);

export const sidebarSecondaryDestinations = productNavigationItems.filter(
  (item) => item.id !== "chat" && item.id !== "knowledge",
);
