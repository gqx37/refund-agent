/** @type {import('next').NextConfig} */
const nextConfig = {
  // The page is static and ships from the CDN; only /api/* runs a function.
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
