/**
 * Proxy vers l'API FastAPI.
 *
 * Le navigateur ne parle qu'au site (même domaine) : le cookie de session reste « first-party »
 * (pas bloqué comme cookie tiers), pas de CORS, et l'adresse de l'API reste côté serveur.
 * On ajoute aussi l'en-tête qui évite la page d'avertissement de ngrok (offre gratuite).
 */
import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 60; // une recherche d'annonces (Apify) peut prendre jusqu'à ~60 s

const FORWARDED_REQUEST_HEADERS = ["cookie", "content-type", "accept", "accept-language"];
const FORWARDED_RESPONSE_HEADERS = ["content-type", "location", "cache-control"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const backend = process.env.BACKEND_URL?.replace(/\/$/, "");
  if (!backend) {
    return NextResponse.json({ detail: "BACKEND_URL n'est pas configurée sur Vercel." }, { status: 500 });
  }
  const { path } = await ctx.params;
  const search = new URL(req.url).search;
  const target = `${backend}/${path.map(encodeURIComponent).join("/")}${search}`;

  const headers = new Headers({ "ngrok-skip-browser-warning": "1", "user-agent": "WaxMatch-Front/0.1" });
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer(),
      redirect: "manual", // les redirections OAuth (vers Spotify, puis vers le site) passent au navigateur
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "API injoignable : le notebook Colab est-il lancé ?" }, { status: 502 });
  }

  // Tunnel ngrok éteint : page HTML d'erreur -> message clair pour l'interface.
  const type = upstream.headers.get("content-type") ?? "";
  if (upstream.status >= 400 && type.includes("text/html")) {
    return NextResponse.json(
      { detail: "API hors ligne : relance les cellules du notebook Colab." },
      { status: 503 },
    );
  }

  const out = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  return new NextResponse(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
