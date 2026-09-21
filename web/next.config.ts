import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  reactCompiler: false,
  turbopack: {},
  webpack: (config) => {
    config.watchOptions = {
      ...config.watchOptions,
      poll: false,
    };
    return config;
  },
};

export default nextConfig;
