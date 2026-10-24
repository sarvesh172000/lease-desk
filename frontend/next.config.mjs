/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // react-pdf / pdfjs optionally requires `canvas` on the server; we only render
  // PDFs in the browser, so stub it out of every bundle.
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    return config;
  },
};

export default nextConfig;
