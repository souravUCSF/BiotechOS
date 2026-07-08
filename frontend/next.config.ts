import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow reaching the dev server (and its HMR/dev resources) via these hosts,
  // not just localhost — otherwise Next 16 blocks the client runtime cross-origin
  // and the app never hydrates. Add your machine's hostnames / LAN IPs here.
  allowedDevOrigins: ["claw.local", "*.local", "localhost", "127.0.0.1"],
};

export default nextConfig;
