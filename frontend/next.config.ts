import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            // Google sign-in opens a popup and Firebase polls window.closed
            // on it to tell "the user cancelled" from "still deciding".
            // Under the browser's stricter default that poll is blocked, so
            // Firebase can wrongly decide the popup closed and abandon a
            // sign-in that was still in progress.
            //
            // same-origin-allow-popups keeps the page isolated from other
            // origins while preserving the opener link to popups this page
            // itself opened, which is exactly what the flow needs.
            key: "Cross-Origin-Opener-Policy",
            value: "same-origin-allow-popups",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
