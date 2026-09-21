export type AppBrandKey = "bothesis";

export const appBrandKey: AppBrandKey = "bothesis";
export const PRODUCT_NAME = "BoThesis";
export const PLATFORM_NAME = "BoThesis";

export const appBrand = {
  key: appBrandKey,
  shortName: PRODUCT_NAME,
  productName: PRODUCT_NAME,
  platformName: PLATFORM_NAME,
  controlPlaneName: "Control Plane",
  controlPlaneSubtitle: "Control plane",
  workspaceSubtitle: "Enterprise knowledge workspace",
  logo: {
    src: "/bothesis-logo.png",
    alt: `${PRODUCT_NAME} logo`,
    imageClassName: "object-contain",
  },
} as const;
