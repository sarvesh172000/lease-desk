/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Hosted (docs/DEPLOY.md): the API lives on another site, and its session
  // cookie is SameSite=Lax, which a browser never sends on a cross-site fetch.
  // So /api is proxied through this app: the browser only ever talks to this
  // origin (set NEXT_PUBLIC_API_URL to it) and the cookie is first-party.
  // Unset locally, where the app calls the API directly.
  async rewrites() {
    const api = (process.env.LEASEDESK_API_ORIGIN || "").replace(/\/$/, "");
    return api ? [{ source: "/api/:path*", destination: `${api}/api/:path*` }] : [];
  },
  // react-pdf / pdfjs optionally requires `canvas` on the server; we only render
  // PDFs in the browser, so stub it out of every bundle.
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    // pdfjs-dist ships ESM-only (.mjs). Webpack treats .mjs as strict ESM and
    // chokes on pdf.mjs ("Object.defineProperty called on non-object"), which
    // takes the whole document viewer down; javascript/auto lets it through.
    config.module.rules.push({ test: /\.mjs$/, include: /node_modules/, type: "javascript/auto" });
    return config;
  },
};

export default nextConfig;
