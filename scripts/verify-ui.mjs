const baseUrl = (process.env.UI_BASE_URL ?? "http://127.0.0.1:3000").replace(/\/$/, "");

function fail(message) {
  console.error(`[UI 自检失败] ${message}`);
  process.exit(1);
}

try {
  const pageResponse = await fetch(`${baseUrl}/`, {
    signal: AbortSignal.timeout(4000),
    headers: { "Cache-Control": "no-cache" },
  });

  if (!pageResponse.ok) fail(`主页返回 HTTP ${pageResponse.status}`);

  const html = await pageResponse.text();
  if (!/<main[^>]+class="[^"]*\bapp-shell\b/.test(html)) fail("主页缺少应用外壳，可能返回了错误页面");

  const stylesheets = [...html.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g)]
    .map((match) => match[1]);

  if (!stylesheets.length) fail("主页没有加载任何样式表");

  const cssResponses = await Promise.all(
    stylesheets.map(async (href) => {
      const url = new URL(href, `${baseUrl}/`);
      const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
      return { href, response, css: response.ok ? await response.text() : "" };
    }),
  );

  const unavailable = cssResponses.find(({ response }) => !response.ok);
  if (unavailable) fail(`样式资源 ${unavailable.href} 返回 HTTP ${unavailable.response.status}`);

  if (!cssResponses.some(({ css }) => css.includes(".app-shell"))) {
    fail("样式表可访问，但缺少产品界面的核心样式");
  }

  if (!cssResponses.some(({ css }) => css.includes(".theme-night") && css.includes("alpaca-snapshot.webp"))) {
    fail("样式表可访问，但缺少 ESO ALPACA 实拍夜空主题");
  }

  if (!cssResponses.some(({ css }) => css.includes(".kb-workbench") && css.includes(".detail-drawer"))) {
    fail("样式表可访问，但缺少知识库工作台与详情抽屉样式");
  }

  const skyMetadataResponse = await fetch(`${baseUrl}/api/sky/latest`, { signal: AbortSignal.timeout(4000) });
  if (!skyMetadataResponse.ok) fail(`夜空元数据返回 HTTP ${skyMetadataResponse.status}`);
  const skyMetadata = await skyMetadataResponse.json();
  if (skyMetadata.provider !== "ESO" || skyMetadata.instrument !== "ALPACA") fail("夜空元数据不是 ESO ALPACA 科学帧");
  if (!skyMetadata.dpId || !skyMetadata.capturedAt || !Number.isFinite(skyMetadata.sqmZen)) fail("夜空元数据缺少观测 ID、时间或 SQM");

  const skyResponse = await fetch(new URL(skyMetadata.imageUrl, `${baseUrl}/`), { signal: AbortSignal.timeout(6000) });
  if (!skyResponse.ok) fail(`夜空背景返回 HTTP ${skyResponse.status}`);
  if (!skyResponse.headers.get("content-type")?.includes("image/webp")) fail("夜空背景的媒体类型不是 image/webp");
  const skyBytes = Number(skyResponse.headers.get("content-length") ?? 0);
  if (skyBytes && skyBytes < 100_000) fail("夜空背景文件异常小，可能是错误页面");

  console.log(`[UI 自检通过] 主页、${stylesheets.length} 个样式资源、知识库工作台与 ESO ALPACA 夜空背景均正常`);
} catch (error) {
  fail(error instanceof Error ? error.message : "无法连接界面服务");
}
