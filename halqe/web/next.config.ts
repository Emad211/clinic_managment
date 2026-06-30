import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // RTL-ready; no CDN — all assets served locally (vazirmatn vendored in
  // public/fonts; no next/font/google, no assetPrefix).
  // output: "standalone" → `next build` emits .next/standalone/server.js with a
  // minimal node_modules, for a lean production Docker image (step 79 / T1).
  output: "standalone",
};

export default nextConfig;
