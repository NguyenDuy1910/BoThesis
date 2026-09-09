export type AppBrandKey = "bothesis";

export const appBrandKey: AppBrandKey = "bothesis";

export const appBrand = {
  key: appBrandKey,
  shortName: "Enterprise Knowledge Agent",
  productName: "Enterprise Knowledge Agent",
  adminName: "Admin Console",
  adminSubtitle: "Control plane",
  workspaceSubtitle: "Enterprise knowledge workspace",
  logo: {
    src: "/bothesis-logo.png",
    alt: "Enterprise Knowledge Agent logo",
    imageClassName: "object-contain",
  },
} as const;
