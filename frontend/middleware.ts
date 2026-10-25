import { NextResponse, type NextRequest } from "next/server";

/** The API's session cookie (backend/app/auth/sessions.py COOKIE_NAME). */
export const SESSION_COOKIE = "leasedesk_session";

/**
 * The front door: a visitor with no session sees the welcome page, not the sign-in form.
 *
 * Only `/`, and only when there is no cookie at all. A deep link still goes through the app's
 * own check (AppShell), which asks to sign in and comes back; a stale cookie lands there too.
 * Fixtures mode never has a session, so it keeps opening on Today.
 */
export function middleware(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_USE_FIXTURES === "1") return NextResponse.next();
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  return NextResponse.redirect(new URL("/welcome", request.url));
}

export const config = { matcher: "/" };
