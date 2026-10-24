/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
