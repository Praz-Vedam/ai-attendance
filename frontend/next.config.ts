import type { NextConfig } from "next";

import { assertVercelApiEnv } from "./lib/vercel-env-check";

assertVercelApiEnv();

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.20.54"],
};

export default nextConfig;
