/** @type {import('next').NextConfig} */
const devApiProxyTarget = (process.env.NEXT_DEV_API_PROXY_URL || "http://127.0.0.1:8000")
  .trim()
  .replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    if (process.env.NODE_ENV !== "development") {
      return [];
    }

    return [
      {
        source: "/api/v1/:path*",
        destination: `${devApiProxyTarget}/api/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
