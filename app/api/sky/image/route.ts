import { readFile } from "node:fs/promises";
import path from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const liveImage = path.join(process.cwd(), "data", "sky", "current.webp");
const bundledImage = path.join(process.cwd(), "public", "sky", "alpaca-snapshot.webp");

export async function GET() {
  let source = liveImage;
  try {
    await readFile(source);
  } catch {
    source = bundledImage;
  }

  try {
    const image = await readFile(source);
    return new Response(image, {
      headers: {
        "Content-Type": "image/webp",
        "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400",
      },
    });
  } catch {
    return new Response("Sky image unavailable", { status: 503 });
  }
}
