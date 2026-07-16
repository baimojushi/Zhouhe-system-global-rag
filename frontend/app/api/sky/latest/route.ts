import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const liveMetadata = path.join(process.cwd(), "data", "sky", "current.json");
const bundledMetadata = path.join(process.cwd(), "public", "sky", "alpaca-snapshot.json");

export async function GET() {
  let source = liveMetadata;
  let fallback = false;

  try {
    await readFile(source);
  } catch {
    source = bundledMetadata;
    fallback = true;
  }

  try {
    const payload = JSON.parse(await readFile(source, "utf8")) as Record<string, unknown>;
    const version = encodeURIComponent(String(payload.dpId ?? payload.capturedAt ?? "fallback"));
    return Response.json(
      {
        ...payload,
        isFallback: fallback || Boolean(payload.isFallback),
        imageUrl: `/api/sky/image?v=${version}`,
        checkedAt: new Date().toISOString(),
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return Response.json({ error: "sky_metadata_unavailable" }, { status: 503 });
  }
}
