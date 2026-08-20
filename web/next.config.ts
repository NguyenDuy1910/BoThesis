import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
