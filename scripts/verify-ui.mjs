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
  if (!html.includes('class="app-shell"')) fail("主页缺少应用外壳，可能返回了错误页面");

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

  console.log(`[UI 自检通过] 主页与 ${stylesheets.length} 个样式资源均正常`);
} catch (error) {
  fail(error instanceof Error ? error.message : "无法连接界面服务");
}
