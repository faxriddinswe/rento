import type { NextConfig } from "next";

const apiInternal = process.env.API_INTERNAL_URL ?? "http://localhost:8010";

const config: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // The browser talks to /api/*; Next proxies it to the FastAPI service (same origin, no CORS).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternal}/:path*` }];
  },
};

export default config;
