export type AppBrandKey = "bothesis";

export const appBrandKey: AppBrandKey = "bothesis";

export const appBrand = {
  key: appBrandKey,
  shortName: "BoThesis",
  productName: "BoThesis",
  adminName: "Admin Console",
  adminSubtitle: "Control plane",
  workspaceSubtitle: "Enterprise knowledge workspace",
  logo: {
    src: "/bothesis-logo.png",
    alt: "BoThesis logo",
    imageClassName: "object-contain",
  },
} as const;
