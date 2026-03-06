import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const configured = (process.env.APP_ADMIN_TOKEN ?? "").trim();
  if (!configured) {
    return NextResponse.json(
      {
        error: {
          code: "auth_not_configured",
          message: "APP_ADMIN_TOKEN is not configured for frontend auth bootstrap",
        },
      },
      { status: 503 },
    );
  }

  const existing = (request.cookies.get("app_admin_token")?.value ?? "").trim();
  const response = new NextResponse(null, { status: 204 });
  if (existing === configured) {
    return response;
  }

  response.cookies.set({
    name: "app_admin_token",
    value: configured,
    httpOnly: true,
    sameSite: "lax",
    secure: request.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 12,
  });
  return response;
}
