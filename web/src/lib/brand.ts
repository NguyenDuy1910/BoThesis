export type AppBrandKey = "bothesis";

export const appBrandKey: AppBrandKey = "bothesis";
export const PRODUCT_NAME = "Enterprise Agent";

export const appBrand = {
  key: appBrandKey,
  shortName: PRODUCT_NAME,
  productName: PRODUCT_NAME,
  adminName: "Admin Console",
  adminSubtitle: "Control plane",
  workspaceSubtitle: "Enterprise knowledge workspace",
  logo: {
    src: "/bothesis-logo.png",
    alt: `${PRODUCT_NAME} logo`,
    imageClassName: "object-contain",
  },
} as const;
