"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { KnowledgeWorkbench } from "./knowledge-workbench";

// Classical phrases containing 宙合, from real historical texts
const classicalPhrases: { text: string; source: string }[] = [
  { text: "圣贯天地，宙合百家，虫人万千，内外精粗", source: "恽敬《伊公祠堂碑铭》" },
  { text: "怀抱芳馨兰一握，纵横宙合雾千重", source: "康有为《出都留别诸公》" },
  { text: "宙合大矣，四部书未经目者，如恒河沙数", source: "平步青《霞外捃屑》" },
  { text: "充宙合之事理，而条贯之", source: "晚清文" },
  { text: "举凡宙合之事理，皆可推而行之", source: "晚清文" },
  { text: "合络天地，以为一裹", source: "《管子·宙合》" },
  { text: "大之无外，小之无内", source: "《管子·宙合》" },
];

function randomPhrase(): { text: string; source: string } {
  return classicalPhrases[Math.floor(Math.random() * classicalPhrases.length)];
}

type View = "search" | "library" | "memory" | "status" | "settings";
type HealthState = "online" | "offline" | "checking";
type ServiceKey = "gateway" | "weaviate" | "llm";

type SearchResult = {
  id: string;
  title: string;
  heading: string;
  content: string;
  sourcePath: string;
  sourceName: string;
  score: number;
  page?: number;
  scope: string;
  tags: string[];
};

type Settings = {
  demoMode: boolean;
  theme: "light" | "night";
  stellarDensity: number;
  limitingMagnitude: number;
  twinkleStrength: number;
  glassOpacity: number;
  galaxyExposure: number;
  syntheticOverlay: boolean;
  gatewayUrl: string;
  weaviateUrl: string;
  llmUrl: string;
  apiKey: string;
  model: string;
  llmApiUrl: string;
  llmApiKey: string;
  llmModel: string;
};

const defaultSettings: Settings = {
  demoMode: true,
  theme: "light",
  stellarDensity: 1,
  limitingMagnitude: 7.2,
  twinkleStrength: 28,
  glassOpacity: 24,
  galaxyExposure: 82,
  syntheticOverlay: false,
  gatewayUrl: "http://127.0.0.1:9100",
  weaviateUrl: "http://127.0.0.1:8080",
  llmUrl: "http://127.0.0.1:8000",
  apiKey: "",
  model: "gemma-4-31b-q4",
  llmApiUrl: "",
  llmApiKey: "",
  llmModel: "qwen-plus",
};

const settingsStorageKey = "global-rag-settings";
const legacyGatewayUrls = new Map([
  ["http://127.0.0.1:8090", "http://127.0.0.1:9100"],
  ["http://localhost:8090", "http://localhost:9100"],
]);

type SkyFrame = {
  provider: string;
  instrument: string;
  site: string;
  dpId: string;
  capturedAt: string;
  exposureSeconds: number;
  sqmZen: number;
  sourceWidth: number;
  sourceHeight: number;
  status: "latest-qualified" | "bundled-fallback";
  isFallback: boolean;
  imageUrl: string;
  credit: string;
  sourcePage: string;
};

const fallbackSkyFrame: SkyFrame = {
  provider: "ESO",
  instrument: "ALPACA",
  site: "Paranal Observatory, Chile",
  dpId: "ALPACA.2026-07-16T06:56:52.000",
  capturedAt: "2026-07-16T06:56:52.000Z",
  exposureSeconds: 120,
  sqmZen: 22,
  sourceWidth: 8750,
  sourceHeight: 8750,
  status: "bundled-fallback",
  isFallback: true,
  imageUrl: "/sky/alpaca-snapshot.webp",
  credit: "ESO / ALPACA",
  sourcePage: "https://archive.eso.org/cms/eso-archive-news/alpaca-all-sky-images-from-paranal-available-in-the-archive.html",
};

const demoResults: SearchResult[] = [
  {
    id: "rag-deployment",
    title: "WSL2 全局混合检索与上下文记忆部署方案",
    heading: "检索流程与参数",
    content:
      "一般中文知识问答建议将混合检索 alpha 设为 0.55；概念和语义性问题可提高到 0.65–0.75。先召回 30 条，重排并扩展相邻切片后，最终返回 6–10 条可靠依据。",
    sourcePath: "/opt/global-rag/kb/WSL2-Global-RAG-Deployment-CN.md",
    sourceName: "WSL2-Global-RAG-Deployment-CN.md",
    score: 0.94,
    scope: "global",
    tags: ["部署文档", "混合检索"],
  },
  {
    id: "gemma-guide",
    title: "WSL2 + llama.cpp 部署 Gemma 4 31B 指南",
    heading: "故障排查 · Gemma Q4 服务启动",
    content:
      "Gemma 4 31B Q4 通过 llama.cpp server 提供 OpenAI 兼容接口。当前运行配置监听 8000，启动入口为 F:\\scripts\\Gemma\\start_q4_server_persistent_v4.bat。",
    sourcePath: "~/docs/Gemma4-31B-Vector-RAG-Implementation-Plan-CN.md",
    sourceName: "Gemma4-31B-Vector-RAG-Implementation-Plan-CN.md",
    score: 0.89,
    scope: "global",
    tags: ["部署文档", "llama.cpp", "Gemma"],
  },
  {
    id: "resource-plan",
    title: "检索栈资源与隔离策略",
    heading: "硬件与资源分配",
    content:
      "两张 3090 完全保留给大语言模型；Weaviate 限制约 14 GB 内存，CPU Embedding 服务限制约 6 GB。数据库应放在 WSL2 ext4，而不是 /mnt/c 或 /mnt/d。",
    sourcePath: "/opt/global-rag/kb/WSL2-Global-RAG-Deployment-CN.md",
    sourceName: "WSL2-Global-RAG-Deployment-CN.md",
    score: 0.82,
    scope: "global",
    tags: ["资源规划", "WSL2"],
  },
];

const navItems: { id: View; label: string; sub: string; icon: IconName }[] = [
  { id: "search", label: "知识检索", sub: "查资料、整理回答", icon: "search" },
  { id: "library", label: "知识库管理", sub: "整理分类和资料", icon: "book" },
  { id: "memory", label: "长期记忆", sub: "保存重要事实和决定", icon: "message" },
  { id: "status", label: "运行状态", sub: "检查和重启服务", icon: "pulse" },
  { id: "settings", label: "系统设置", sub: "连接地址和显示方式", icon: "settings" },
];

type IconName = "search" | "book" | "message" | "pulse" | "settings" | "quote" | "path" | "plus" | "trash" | "check" | "arrow" | "spark" | "copy" | "sun" | "moon" | "restart";

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, React.ReactNode> = {
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16M8 7h8M8 11h7"/></>,
    message: <><path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/><path d="M8 9h.01M12 9h.01M16 9h.01"/></>,
    pulse: <><path d="M3 12h4l2.2-6 4.3 12 2.2-6H21"/><circle cx="12" cy="12" r="10"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V21h-4v-.08A1.7 1.7 0 0 0 8.95 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.58 15 1.7 1.7 0 0 0 3 14H3v-4h.08A1.7 1.7 0 0 0 4.6 8.95a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.58 1.7 1.7 0 0 0 10 3V3h4v.08A1.7 1.7 0 0 0 15.05 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.42 9 1.7 1.7 0 0 0 21 10h.08v4H21a1.7 1.7 0 0 0-1.6 1z"/></>,
    quote: <><path d="M9 11H5a4 4 0 0 0 4 4V7H5v4M19 11h-4a4 4 0 0 0 4 4V7h-4v4"/></>,
    path: <><circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h3a3 3 0 0 0 3-3V9a3 3 0 0 1 3-3"/></>,
    plus: <path d="M12 5v14M5 12h14"/>,
    trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
    spark: <><path d="m12 3 1.2 4.1L17 9l-3.8 1.9L12 15l-1.2-4.1L7 9l3.8-1.9z"/><path d="m18.5 14 .7 2.3 2.3.7-2.3.7-.7 2.3-.7-2.3-2.3-.7 2.3-.7z"/></>,
    copy: <><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></>,
    sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.66 6.34l1.41-1.41"/></>,
    moon: <path d="M20.4 15.5A8.3 8.3 0 0 1 8.5 3.6a8.4 8.4 0 1 0 11.9 11.9Z"/>,
    restart: <><path d="M21 12a9 9 0 0 0-9-9 9.8 9.8 0 0 0-6.6 2.6L3 7"/><path d="M3 7v6h6"/><path d="M3 13a9 9 0 0 0 9 9 9.8 9.8 0 0 0 6.6-2.6L21 17"/><path d="M21 17v-6h-6"/></>,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function DeepSpaceBackdrop({ active, overlay, imageUrl, density, limitingMagnitude, twinkle }: { active: boolean; overlay: boolean; imageUrl: string; density: number; limitingMagnitude: number; twinkle: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!active || !overlay) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;
    const surface = canvas;
    const drawing = context;

    type Star = { x: number; y: number; magnitude: number; radius: number; alpha: number; phase: number; speed: number; amplitude: number; color: string };
    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let stars: Star[] = [];
    let animationFrame = 0;
    let lastPaint = 0;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const minMagnitude = -1.46;

    function rebuildStars() {
      const magnitudeFactor = Math.min(2.4, Math.pow(10, 0.15 * (limitingMagnitude - 6.5)));
      const count = Math.min(1200, Math.max(80, Math.round((width * height / 10500) * density * magnitudeFactor)));
      const minPopulation = Math.pow(10, 0.6 * minMagnitude);
      const maxPopulation = Math.pow(10, 0.6 * limitingMagnitude);
      stars = Array.from({ length: count }, () => {
        const population = minPopulation + Math.random() * (maxPopulation - minPopulation);
        const magnitude = Math.log10(population) / 0.6;
        const flux = Math.pow(10, -0.4 * (magnitude - minMagnitude));
        const temperature = Math.random();
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          magnitude,
          radius: 0.38 + Math.pow(flux, 0.2) * 1.55,
          alpha: 0.09 + Math.pow(flux, 0.22) * 0.78,
          phase: Math.random() * Math.PI * 2,
          speed: 0.0001 + Math.random() * 0.00016,
          amplitude: (twinkle / 100) * (0.025 + Math.random() * 0.075),
          color: temperature < 0.16 ? "255,183,196" : temperature > 0.84 ? "218,226,255" : "255,244,242",
        };
      });
    }

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 1.6);
      surface.width = Math.round(width * pixelRatio);
      surface.height = Math.round(height * pixelRatio);
      surface.style.width = `${width}px`;
      surface.style.height = `${height}px`;
      drawing.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      rebuildStars();
    }

    function paint(time: number) {
      if (time - lastPaint < 42 && !reduceMotion) {
        animationFrame = requestAnimationFrame(paint);
        return;
      }
      lastPaint = time;
      drawing.clearRect(0, 0, width, height);
      for (const star of stars) {
        const pulse = reduceMotion ? 0 : Math.sin(time * star.speed + star.phase) * star.amplitude;
        const alpha = Math.max(0.035, Math.min(0.96, star.alpha + pulse));
        if (star.magnitude < 1.4) {
          const glow = drawing.createRadialGradient(star.x, star.y, 0, star.x, star.y, star.radius * 5.5);
          glow.addColorStop(0, `rgba(${star.color},${alpha * 0.62})`);
          glow.addColorStop(0.2, `rgba(255,37,70,${alpha * 0.14})`);
          glow.addColorStop(1, "rgba(255,0,32,0)");
          drawing.fillStyle = glow;
          drawing.beginPath();
          drawing.arc(star.x, star.y, star.radius * 5.5, 0, Math.PI * 2);
          drawing.fill();
        }
        drawing.fillStyle = `rgba(${star.color},${alpha})`;
        drawing.beginPath();
        drawing.arc(star.x, star.y, star.radius, 0, Math.PI * 2);
        drawing.fill();
      }
      if (!reduceMotion) animationFrame = requestAnimationFrame(paint);
    }

    resize();
    paint(0);
    window.addEventListener("resize", resize, { passive: true });
    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animationFrame);
    };
  }, [active, overlay, density, limitingMagnitude, twinkle]);

  return <div className="deep-space-backdrop" aria-hidden="true" style={{ "--sky-image": `url("${imageUrl}")` } as React.CSSProperties}>{overlay && <canvas ref={canvasRef}/>}<span className="space-vignette"/></div>;
}

function toResult(item: Record<string, unknown>, index: number): SearchResult {
  const props = (item.properties ?? item) as Record<string, unknown>;
  return {
    id: String(item.id ?? props.chunk_id ?? index),
    title: String(props.title ?? props.source_name ?? "未命名来源"),
    heading: String(props.heading ?? "正文"),
    content: String(props.content ?? props.text ?? ""),
    sourcePath: String(props.source_path ?? props.path ?? ""),
    sourceName: String(props.source_name ?? props.title ?? "来源"),
    score: Number(item.score ?? props.score ?? item.certainty ?? 0),
    page: props.page == null ? undefined : Number(props.page),
    scope: String(props.scope ?? "global"),
    tags: Array.isArray(props.tags) ? props.tags.map(String) : [String(props.mime_type ?? "知识片段")],
  };
}

export default function Home() {
  const [heroPhrase] = useState(randomPhrase);
  const [view, setView] = useState<View>("search");
  const [settings, setSettings] = useState<Settings>(defaultSettings);
  const [skyFrame, setSkyFrame] = useState<SkyFrame>(fallbackSkyFrame);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState("all");
  const [alpha, setAlpha] = useState(65);
  const [topK, setTopK] = useState(6);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [answer, setAnswer] = useState("");
  const [answering, setAnswering] = useState(false);
  const [sessionId, setSessionId] = useState("local-main");
  const [memoryText, setMemoryText] = useState("");
  const [health, setHealth] = useState<Record<ServiceKey, HealthState>>({ gateway: "online", weaviate: "online", llm: "online" });
  const [llmApiHealth, setLlmApiHealth] = useState<HealthState>("checking");
  const [llmApiInfo, setLlmApiInfo] = useState<{ model?: string; latency_ms?: number; error?: string }>({});
  const [lastCheck, setLastCheck] = useState("刚刚");
  const [restarting, setRestarting] = useState<Set<string>>(new Set());

  useEffect(() => {
    const saved = localStorage.getItem(settingsStorageKey);
    if (!saved) return;

    let restored: Settings;
    let migrated = false;
    try {
      const parsed = JSON.parse(saved) as Partial<Settings> & { vllmUrl?: string; embeddingUrl?: string };
      const legacyGatewayUrl = typeof parsed.gatewayUrl === "string" ? legacyGatewayUrls.get(parsed.gatewayUrl) : undefined;
      const legacyLlmUrl = typeof parsed.vllmUrl === "string" ? parsed.vllmUrl : undefined;
      restored = { ...defaultSettings, ...parsed, ...(legacyGatewayUrl ? { gatewayUrl: legacyGatewayUrl } : {}), ...(legacyLlmUrl ? { llmUrl: legacyLlmUrl } : {}) };
      migrated = Boolean(legacyGatewayUrl || legacyLlmUrl || parsed.embeddingUrl);
    }
    catch { return; }

    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setSettings(restored);
      if (migrated) localStorage.setItem(settingsStorageKey, JSON.stringify(restored));
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function refreshSky() {
      try {
        const response = await fetch("/api/sky/latest", { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json() as SkyFrame;
        if (!cancelled) setSkyFrame({ ...fallbackSkyFrame, ...payload });
      } catch {
        // Keep the bundled scientific frame when the hourly updater is unavailable.
      }
    }
    refreshSky();
    const timer = window.setInterval(refreshSky, 60 * 60 * 1000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [view]);

  const selectedResults = useMemo(() => results.filter((item) => selected.includes(item.id)), [results, selected]);

  function saveSettings(next: Settings) {
    setSettings(next);
    localStorage.setItem(settingsStorageKey, JSON.stringify(next));
  }

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 2400);
  }

  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setHasSearched(true);
    setResults([]);
    setSelected([]);
    setAnswer("");
    try {
      if (settings.demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 620));
        const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
        const ranked = demoResults
          .map((item) => ({ ...item, score: Math.min(.98, item.score + (terms.some((term) => `${item.title}${item.content}`.toLowerCase().includes(term)) ? .02 : 0)) }))
          .slice(0, topK);
        setResults(ranked);
      } else {
        const response = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/retrieve`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(settings.apiKey ? { Authorization: `Bearer ${settings.apiKey}` } : {}) },
          body: JSON.stringify({ query, scope: scope === "all" ? undefined : scope, alpha: alpha / 100, top_k: topK, session_id: sessionId }),
        });
        if (!response.ok) throw new Error(`检索失败：HTTP ${response.status}`);
        const payload = await response.json() as Record<string, unknown>;
        const items = (payload.results ?? payload.items ?? payload.data ?? []) as Record<string, unknown>[];
        setResults(items.map(toResult));
      }
    } catch (error) {
      flash(error instanceof Error ? error.message : "无法连接检索服务");
    } finally {
      setLoading(false);
    }
  }

  async function checkHealth() {
    setHealth({ gateway: "checking", weaviate: "checking", llm: "checking" });
    setLlmApiHealth("checking");
    if (settings.demoMode) {
      await new Promise((resolve) => window.setTimeout(resolve, 520));
      setHealth({ gateway: "online", weaviate: "online", llm: "online" });
      setLlmApiHealth("online");
      setLastCheck("刚刚");
      return;
    }
    const checks: [ServiceKey, string, Record<string, string>?][] = [
      ["gateway", `${settings.gatewayUrl}/health`],
      ["weaviate", `${settings.weaviateUrl}/v1/.well-known/ready`, settings.apiKey ? { Authorization: `Bearer ${settings.apiKey}` } : undefined],
      ["llm", `${settings.llmUrl}/health`],
    ];
    const states = await Promise.all(checks.map(async ([key, url, headers]) => {
      try { const response = await fetch(url, { headers }); return [key, response.ok ? "online" : "offline"] as const; }
      catch { return [key, "offline"] as const; }
    }));
    setHealth(Object.fromEntries(states) as Record<ServiceKey, HealthState>);
    // Check LLM API connectivity
    if (settings.llmApiUrl && settings.llmApiKey) {
      try {
        await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/llm/config`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ llm_api_base: settings.llmApiUrl, llm_api_key: settings.llmApiKey, llm_model: settings.llmModel }),
        });
        const resp = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/llm/test`);
        const result = await resp.json() as { ok?: boolean; latency_ms?: number; model?: string; error?: string; model_found?: boolean };
        setLlmApiHealth(result.ok ? "online" : "offline");
        setLlmApiInfo({ model: result.model, latency_ms: result.latency_ms, error: result.error });
      } catch {
        setLlmApiHealth("offline");
        setLlmApiInfo({ error: "无法连接 Gateway" });
      }
    } else {
      setLlmApiHealth("offline");
      setLlmApiInfo({ error: "未配置" });
    }
    setLastCheck(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }));
  }

  async function handleRestart(service: "gateway" | "weaviate" | "llm" | "all", profile?: "q4" | "q8") {
    const key = service === "llm" ? "gemma" : service;
    setRestarting((prev) => new Set(prev).add(key));
    try {
      const response = await fetch("/api/services/restart", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ service: key, profile }),
      });
      const data = await response.json() as { ok?: boolean; message?: string; error?: string };
      if (!response.ok || !data.ok) {
        flash(data.error || data.message || "重启失败");
      } else {
        flash(data.message || `${service === "llm" ? "Gemma" : service === "all" ? "全部服务" : "服务"}正在重启…`);
        // Re-check health after delay
        await new Promise((resolve) => setTimeout(resolve, service === "all" ? 12000 : 6000));
        await checkHealth();
      }
    } catch (error) {
      flash(error instanceof Error ? error.message : "重启请求失败");
    } finally {
      setRestarting((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  }

  function toggleCitation(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
    flash(selected.includes(id) ? "已移出引用" : "已加入回答上下文");
  }

  async function generateAnswer() {
    const context = (selectedResults.length ? selectedResults : results.slice(0, 3));
    if (!context.length) return;
    setAnswering(true);
    try {
      if (settings.demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 780));
        setAnswer("部署时由 RAG Gateway 统一编排 Weaviate、进程内 BGE-M3 与 llama.cpp Gemma：BGE-M3 只负责向量化，Gemma 负责问题分类、检索规划与带依据回答。当前 Gemma Q4 服务默认监听 8000；浏览器最终只访问 Gateway 9100，模型密钥和检索细节不下发前端。数据库与模型文件应放在 WSL2 ext4 中。［1］［2］［3］");
      } else {
        const messages = [
          { role: "system", content: "你是本地知识库助手。只根据给出的检索片段回答，使用［序号］标注依据。" },
          { role: "user", content: `问题：${query}\n\n检索片段：\n${context.map((item, i) => `［${i + 1}］${item.title} / ${item.heading}\n${item.content}`).join("\n\n")}` },
        ];
        const response = await fetch(`${settings.llmUrl.replace(/\/$/, "")}/v1/chat/completions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: settings.model, messages, temperature: 0.2, max_tokens: 900 }),
        });
        if (!response.ok) throw new Error(`生成失败：HTTP ${response.status}`);
        const data = await response.json() as { choices?: { message?: { content?: string } }[] };
        setAnswer(data.choices?.[0]?.message?.content ?? "模型没有返回内容。");
      }
    } catch (error) { flash(error instanceof Error ? error.message : "生成失败"); }
    finally { setAnswering(false); }
  }

  async function postGateway(path: string, body: Record<string, unknown>, success: string) {
    if (settings.demoMode) { await new Promise((resolve) => window.setTimeout(resolve, 420)); flash(success); return; }
    try {
      const response = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(settings.apiKey ? { Authorization: `Bearer ${settings.apiKey}` } : {}) },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`请求失败：HTTP ${response.status}`);
      flash(success);
    } catch (error) { flash(error instanceof Error ? error.message : "请求失败"); }
  }

  const skyCapturedLabel = new Date(skyFrame.capturedAt).toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "UTC", hour12: false,
  });

  return (
    <main
      className={`app-shell ${settings.theme === "night" ? "theme-night" : "theme-light"}`}
      style={{
        "--glass-alpha": (settings.glassOpacity / 100).toFixed(2),
        "--galaxy-exposure": (settings.galaxyExposure / 100).toFixed(2),
      } as React.CSSProperties}
    >
      <DeepSpaceBackdrop active={settings.theme === "night"} overlay={settings.syntheticOverlay} imageUrl={skyFrame.imageUrl} density={settings.stellarDensity} limitingMagnitude={settings.limitingMagnitude} twinkle={settings.twinkleStrength}/>
      <aside className="sidebar">
        <div className="brand" aria-label="宙合知识管理工作台">
          <span className="brand-seal">宙</span>
          <span className="brand-copy"><b>宙合</b><small>知识检索与管理</small></span>
        </div>
        <nav aria-label="主导航">
          {navItems.map((item) => (
            <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>
              <span className="nav-icon"><Icon name={item.icon} size={22}/></span>
              <span><b>{item.label}</b><small>{item.sub}</small></span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className={`mode-mark ${settings.demoMode ? "demo" : "live"}`}/>
          <span><b>{settings.demoMode ? "演示模式" : "本地服务"}</b><small>{settings.demoMode ? "无需后端即可体验" : "连接 127.0.0.1"}</small></span>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="mobile-brand"><span className="brand-seal">宙</span><b>宙合</b></div>
          <div className="service-strip">
            {([ ["weaviate", "资料索引", "运行服务"], ["gateway", "资料理解", "内置"], ["llm", "本地回答", "运行服务"] ] as [ServiceKey, string, string][]).map(([key, label, meta]) => (
              <div key={key} className="service-pill-wrapper">
                <button className="service-pill" onClick={() => setView("status")} title={`查看 ${label} 服务状态`}>
                  <span className={`status-dot ${health[key]}`}/><span>{label}</span><small>{meta}</small>
                </button>
                <button
                  className="service-restart"
                  onClick={() => handleRestart(key, key === "llm" ? undefined : undefined)}
                  disabled={restarting.has(key)}
                  title={`重启 ${label} 服务`}
                >
                  {restarting.has(key) ? <span className="loading-mark"/> : <Icon name="restart" size={15}/>}
                </button>
              </div>
            ))}
          </div>
          <div className="top-actions">
            <span className="session-label">会话 · {sessionId}</span>
            <button
              className="quiet-button theme-toggle"
              aria-pressed={settings.theme === "night"}
              onClick={() => saveSettings({ ...settings, theme: settings.theme === "night" ? "light" : "night" })}
              title={settings.theme === "night" ? "切换到日间模式" : "切换到深空模式"}
            >
              <Icon name={settings.theme === "night" ? "sun" : "moon"} size={18}/><span>{settings.theme === "night" ? "日间模式" : "深空模式"}</span>
            </button>
            <button className="quiet-button" onClick={() => setView("settings")}><Icon name="settings" size={18}/><span>连接设置</span></button>
          </div>
        </header>

        {settings.theme === "night" && <a className="sky-telemetry" href={skyFrame.sourcePage} target="_blank" rel="noreferrer" title={`科学帧 ${skyFrame.dpId}`}>
          <span className={`sky-live-dot ${skyFrame.isFallback ? "fallback" : "live"}`}/>
          <span><b>{skyFrame.isFallback ? "最近可用夜空" : "每小时实拍夜空"}</b><small>{skyFrame.instrument} · 帕拉纳尔 · {skyCapturedLabel}（世界协调时）</small></span>
          <span><b>{skyFrame.sqmZen.toFixed(2)}</b><small>mag/arcsec²</small></span>
          <span><b>{skyFrame.sourceWidth}²</b><small>原始像素</small></span>
        </a>}

        {view === "search" && (
          <div className="page search-page">
            <section className="search-column">
              <div className="eyebrow"><span/>从你的资料中寻找答案</div>
              <div className="hero-quote-container">
                <h1 className="hero-quote">「{heroPhrase.text}」</h1>
                <p className="hero-source">—— {heroPhrase.source}</p>
              </div>
              <p className="intro">个人终生知识库</p>

              <form onSubmit={runSearch} className="search-form">
                <label className="query-box">
                  <span className="query-icon"><Icon name="search" size={28}/></span>
                  <textarea aria-label="检索问题" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runSearch(); } }} placeholder="输入问题、错误码、文件名或命令…"/>
                  <span className="key-hint">Enter 检索 · Shift + Enter 换行</span>
                </label>

                <div className="control-grid">
                  <div className="control-block range-block">
                    <label>检索范围</label>
                    <div className="segment-group" role="radiogroup" aria-label="检索范围">
                      {[ ["all", "全部知识"], ["global", "部署文档"], ["private", "会话记忆"] ].map(([value, label]) => <button type="button" role="radio" aria-checked={scope === value} className={scope === value ? "selected" : ""} key={value} onClick={() => setScope(value)}>{label}</button>)}
                    </div>
                  </div>
                  <div className="control-block topk-block">
                    <label htmlFor="top-k">显示几条结果</label>
                    <select id="top-k" value={topK} onChange={(e) => setTopK(Number(e.target.value))}>
                      {[4, 6, 8, 10].map((n) => <option key={n} value={n}>{n} 条</option>)}
                    </select>
                  </div>
                </div>

                <div className="weight-block">
                  <div className="weight-head"><label htmlFor="alpha">更看重哪种匹配方式</label><span><b>理解意思 {alpha}%</b><i>匹配原词 {100 - alpha}%</i></span></div>
                  <input id="alpha" type="range" min="0" max="100" value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} style={{ "--range": `${alpha}%` } as React.CSSProperties}/>
                  <div className="range-notes"><span>适合文件名、错误码</span><span>适合自然语言问题</span></div>
                </div>

                <button className="primary-button" disabled={loading} type="submit">{loading ? <span className="loading-mark"/> : <Icon name="arrow"/>}<span>{loading ? "正在检索" : "开始检索"}</span></button>
              </form>

              <div className="answer-panel">
                <div className="answer-head"><div><span className="section-kicker">整理回答</span><h2>根据资料生成回答</h2></div><button onClick={generateAnswer} disabled={answering || !results.length} className="outline-button"><Icon name="spark"/>{answering ? "正在整理" : "生成回答"}</button></div>
                {answer ? <p className="answer-text">{answer}</p> : !hasSearched ? <div className="answer-empty-state"><span>空</span><div><b>尚未开始检索</b><p>输入问题并完成检索后，可以在这里根据找到的资料生成回答。</p></div></div> : results.length === 0 ? <div className="answer-empty-state"><span>空</span><div><b>暂时没有可用资料</b><p>找到可靠资料后，才可以生成有出处的回答。</p></div></div> : <p className="empty-answer">可以先勾选右侧最可信的资料，再点击“生成回答”。如果不选择，系统会默认使用前三条结果。</p>}
              </div>
            </section>

            <section className="results-column">
              <div className="results-head"><div><span className="section-kicker">找到的资料</span><h2>可用资料</h2></div><div className="result-count"><b>{results.length}</b><span>条结果</span></div></div>
              {hasSearched && results.length > 0 && <div className="citation-summary"><span>已选择 <b>{selected.length}</b> 条用于生成回答</span>{selected.length > 0 && <button onClick={() => setSelected([])}>取消全部选择</button>}</div>}
              <div className="result-list" aria-live="polite">
                {loading && <div className="empty-state search-loading-state"><span className="loading-mark"/><h3>正在查找资料</h3><p>系统正在比较问题与知识库内容。</p></div>}
                {results.map((item, index) => (
                  <article className={`result-card ${selected.includes(item.id) ? "cited" : ""}`} key={item.id} style={{ animationDelay: `${index * 45}ms` }}>
                    <div className="result-meta"><span className="rank">{String(index + 1).padStart(2, "0")}</span><div className="tag-row">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><span className="score">{Math.round(item.score * 100)}<small>%</small></span></div>
                    <h3>{item.title}</h3>
                    <p className="heading">{item.heading}{item.page ? ` · 第 ${item.page} 页` : ""}</p>
                    <p className="excerpt">{item.content}</p>
                    <div className="source-path"><Icon name="path" size={16}/><span title={item.sourceName}>来源 · {item.sourceName}</span></div>
                    <div className="card-foot"><span>相关度</span><div className="score-line"><i style={{ width: `${item.score * 100}%` }}/></div><button onClick={() => toggleCitation(item.id)} className={selected.includes(item.id) ? "selected" : ""}><Icon name={selected.includes(item.id) ? "check" : "quote"} size={17}/>{selected.includes(item.id) ? "已引用" : "引用"}</button></div>
                  </article>
                ))}
                {!loading && !results.length && (hasSearched ? <div className="empty-state"><span>无</span><h3>没有找到可靠资料</h3><p>可以换一种说法、扩大检索范围，或增加显示结果数量。</p></div> : <div className="empty-state search-initial-state"><span>空</span><h3>尚未开始检索</h3><p>输入问题并点击“开始检索”，找到的资料会显示在这里。</p></div>)}
              </div>
            </section>
          </div>
        )}

        {view === "library" && <KnowledgeWorkbench demoMode={settings.demoMode} gatewayUrl={settings.gatewayUrl} apiKey={settings.apiKey} llmApiUrl={settings.llmApiUrl} llmApiKey={settings.llmApiKey} llmModel={settings.llmModel} onNotice={flash}/>} 

        {view === "memory" && (
          <div className="page inner-page">
            <PageTitle kicker="长期记忆" title="记住重要信息" description="把以后还会用到的事实、决定和简短总结保存在这里。普通聊天内容不需要手动保存。"/>
            <div className="memory-layout">
              <section className="paper-panel memory-compose"><PanelHeading number="1" title="保存一条长期记忆" text="保存后，系统可以在以后的问答中重新找到它。"/>
                <label className="field"><span>归属会话</span><input value={sessionId} onChange={(e) => setSessionId(e.target.value)}/><small>用于区分不同项目或对话，可保留默认值。</small></label>
                <label className="field"><span>记忆内容</span><textarea value={memoryText} onChange={(e) => setMemoryText(e.target.value)} placeholder="例如：项目交付前必须先完成离线环境测试。"/></label>
                <div className="memory-actions"><select aria-label="记忆类型"><option>这是一个决定</option><option>这是一个事实</option><option>这是一段总结</option></select><button disabled={!memoryText.trim()} className="primary-button compact" onClick={() => { postGateway("/v1/memory", { content: memoryText, session_id: sessionId, memory_type: "decision", importance: .8, scope: "private" }, "已保存到长期记忆"); setMemoryText(""); }}><Icon name="plus"/>保存</button></div>
              </section>
              <section className="memory-list-panel"><div className="memory-list-head"><span className="section-kicker">最近保存</span><h2>近期记忆</h2></div>
                {[ ["决定", "资料搜索和文字理解由本机服务统一完成。", "今天 18:44"], ["事实", "本地回答模型已经连接，可以根据资料生成回答。", "今天 18:39"], ["总结", "下一版将继续完善自动分类和带出处的回答。", "今天 18:33"] ].map(([type, text, time], i) => <article className="memory-card" key={text}><span>{type}</span><p>{text}</p><footer><i>优先级：{i === 0 ? "高" : i === 1 ? "中" : "普通"}</i><time>{time}</time></footer></article>)}
              </section>
            </div>
          </div>
        )}

        {view === "status" && (
          <div className="page inner-page">
            <div className="title-row"><PageTitle kicker="运行状态" title="系统是否正常运行" description={`上次检查：${lastCheck}。检查不会修改任何服务；只有点击重启按钮才会执行操作。`}/><div className="status-actions"><button className="outline-button" onClick={checkHealth}><Icon name="pulse"/>重新检查</button><button className="outline-button" onClick={() => handleRestart("all")} disabled={restarting.has("all")}>{restarting.has("all") ? "正在重启…" : "重启全部服务"}</button></div></div>
            <div className="status-grid">
              {([ ["gateway", "资料检索服务", settings.gatewayUrl, "负责查找资料、接收新文件并把各项服务连接起来。", "9100"], ["weaviate", "资料索引服务", settings.weaviateUrl, "保存可搜索的资料索引，让关键词和语义搜索都能工作。", "8080"], ["llm", "本地回答模型", settings.llmUrl, "根据找到的资料生成回答，也可协助整理知识库。", "8000"] ] as [ServiceKey, string, string, string, string][]).map(([key, title, url, description, metric], i) => <article className="status-card" key={key}><div className="status-card-top"><span className="ordinal">{i + 1}</span><span className={`large-status ${health[key]}`}>{health[key] === "checking" ? "检查中" : health[key] === "online" ? "运行正常" : "无法连接"}</span></div><h2>{title}</h2><p>{description}</p><details className="technical-details"><summary>查看连接地址</summary><code>{url}</code><footer><span>使用端口</span><b>{health[key] === "online" ? metric : "—"}</b></footer></details><div className="status-card-actions"><button className="outline-button compact-restart" onClick={() => handleRestart(key as "gateway" | "weaviate" | "llm")} disabled={restarting.has(key)}>{restarting.has(key) ? "重启中…" : "重启这项服务"}</button></div></article>)}
              <article className="status-card"><div className="status-card-top"><span className="ordinal">4</span><span className={`large-status ${llmApiHealth}`}>{llmApiHealth === "checking" ? "检查中" : llmApiHealth === "online" ? "连接正常" : "尚未连接"}</span></div><h2>智能分类助手</h2><p>帮助把未整理资料放进合适的分类；所有建议都需要人工确认。</p><details className="technical-details"><summary>查看技术信息</summary><code>{settings.llmApiUrl || "尚未填写服务地址"}</code><footer><span>{llmApiInfo.model || "使用模型"}</span><b>{llmApiHealth === "online" && llmApiInfo.latency_ms ? `${llmApiInfo.latency_ms}ms` : "—"}</b></footer></details></article>
            </div>
            <section className="paper-panel resource-panel"><PanelHeading number="用量" title="资源使用情况" text="用于判断本机是否还有足够资源继续添加资料。"/><div className="resource-bars"><ResourceBar label="资料索引占用内存" value="8.7 / 14 GB" width="62%"/><ResourceBar label="文字理解服务占用内存" value="3.2 / 6 GB" width="53%"/><ResourceBar label="已使用的索引容量" value="34 万 / 80 万" width="42%"/></div></section>
          </div>
        )}

        {view === "settings" && (
          <div className="page inner-page">
            <PageTitle kicker="系统设置" title="连接与显示设置" description="常用设置直接显示；不常使用的技术选项可以按需展开。密码只保存在当前浏览器，不会写入项目源码。"/>
            <section className="paper-panel settings-panel">
              <div className="mode-switch"><div><b>使用哪套数据</b><p>体验模式使用内置样例；本地模式读取你电脑中已经部署好的真实资料。</p></div><button className={settings.demoMode ? "demo" : "live"} onClick={() => saveSettings({ ...settings, demoMode: !settings.demoMode })}><span/><b>{settings.demoMode ? "体验模式" : "本地模式"}</b></button></div>
              <details className="settings-group" open>
                <summary><span><b>本地服务连接</b><small>部署后通常只需设置一次</small></span></summary>
                <div className="settings-grid">
                  <label className="field"><span>资料检索服务地址</span><input value={settings.gatewayUrl} onChange={(e) => setSettings({ ...settings, gatewayUrl: e.target.value })}/><small>默认端口 9100</small></label>
                  <label className="field"><span>资料索引服务地址</span><input value={settings.weaviateUrl} onChange={(e) => setSettings({ ...settings, weaviateUrl: e.target.value })}/><small>默认端口 8080</small></label>
                  <label className="field"><span>本地回答模型地址</span><input value={settings.llmUrl} onChange={(e) => setSettings({ ...settings, llmUrl: e.target.value })}/><small>默认端口 8000</small></label>
                  <label className="field"><span>本地服务访问密码</span><input type="password" value={settings.apiKey} placeholder="由部署脚本生成" onChange={(e) => setSettings({ ...settings, apiKey: e.target.value })}/></label>
                  <label className="field"><span>本地模型名称</span><input value={settings.model} onChange={(e) => setSettings({ ...settings, model: e.target.value })}/></label>
                </div>
              </details>
              <details className="settings-group">
                <summary><span><b>智能分类助手</b><small>可选：连接外部模型帮助整理资料</small></span></summary>
                <p>如果需要自动分类，可填写兼容 OpenAI 格式的模型服务。地址和密码只保存在浏览器中，保存设置时会同步给本地检索服务。</p>
                <div className="settings-grid">
                  <label className="field"><span>模型服务地址</span><input value={settings.llmApiUrl} placeholder="例如通义千问的兼容接口地址" onChange={(e) => setSettings({ ...settings, llmApiUrl: e.target.value })}/></label>
                  <label className="field"><span>模型服务密码</span><input type="password" value={settings.llmApiKey} placeholder="通常以 sk- 开头" onChange={(e) => setSettings({ ...settings, llmApiKey: e.target.value })}/></label>
                  <label className="field"><span>模型名称</span><input value={settings.llmModel} placeholder="例如 qwen-plus" onChange={(e) => setSettings({ ...settings, llmModel: e.target.value })}/></label>
                  <label className="field"><span>测试是否可用</span><button className="outline-button" style={{ width: "100%", height: "46px" }} onClick={async () => {
                    try {
                      await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/llm/config`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ llm_api_base: settings.llmApiUrl, llm_api_key: settings.llmApiKey, llm_model: settings.llmModel }),
                      });
                      const resp = await fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/llm/test`);
                      const result = await resp.json() as { ok?: boolean; latency_ms?: number; model?: string; error?: string; model_found?: boolean };
                      if (result.ok) {
                        flash(`✅ LLM API 连通 · ${result.model} · ${result.latency_ms}ms${result.model_found === false ? " ⚠ 模型名未在列表中" : ""}`);
                      } else {
                        flash(`❌ 连接失败：${result.error || "未知错误"}`);
                      }
                    } catch (e) { flash(`❌ 请求失败：${e instanceof Error ? e.message : "网络错误"}`); }
                  }}>测试分类助手</button></label>
                </div>
              </details>
              <details className="settings-group">
                <summary><span><b>深空背景与显示效果</b><small>可选：调整夜间模式的银河背景</small></span></summary>
                <p>背景来自 ESO 帕拉纳尔 ALPACA 实拍科学帧，每小时检查一次；当地白天或质量不足时保留最近合格夜空并明确标识。</p>
                <div className="sky-source-card">
                  <span className="sky-source-mark">ESO</span>
                  <div><b>ALPACA 全天空科学帧</b><small>{skyFrame.dpId} · SQM {skyFrame.sqmZen.toFixed(2)} mag/arcsec² · {skyFrame.sourceWidth} × {skyFrame.sourceHeight}</small></div>
                  <button className={settings.syntheticOverlay ? "enabled" : ""} onClick={() => setSettings({ ...settings, syntheticOverlay: !settings.syntheticOverlay })}><i/><span>{settings.syntheticOverlay ? "氛围增强已开" : "科研原图模式"}</span></button>
                </div>
                <p className="overlay-disclosure">“科研原图模式”不添加合成星。开启“氛围增强”后，下列选项只改变页面显示，不会修改实拍图片或观测信息。</p>
                <div className={`space-control-grid ${settings.syntheticOverlay ? "" : "controls-muted"}`}>
                  <SpaceControl label="星场密度" value={settings.stellarDensity} min={0.45} max={2} step={0.05} unit="×" onChange={(value) => setSettings({ ...settings, stellarDensity: value })}/>
                  <SpaceControl label="可见暗星数量" value={settings.limitingMagnitude} min={5} max={9} step={0.1} unit="级" onChange={(value) => setSettings({ ...settings, limitingMagnitude: value })}/>
                  <SpaceControl label="闪烁幅度" value={settings.twinkleStrength} min={0} max={100} step={1} unit="%" onChange={(value) => setSettings({ ...settings, twinkleStrength: value })}/>
                  <SpaceControl label="面板透明程度" value={settings.glassOpacity} min={12} max={48} step={1} unit="%" onChange={(value) => setSettings({ ...settings, glassOpacity: value })}/>
                  <SpaceControl label="银河背景亮度" value={settings.galaxyExposure} min={45} max={120} step={1} unit="%" onChange={(value) => setSettings({ ...settings, galaxyExposure: value })}/>
                </div>
              </details>
              <div className="settings-actions"><button className="outline-button" onClick={checkHealth}><Icon name="pulse"/>测试连接</button><button className="primary-button compact" onClick={() => {
                    saveSettings(settings);
                    // Sync LLM config to backend
                    fetch(`${settings.gatewayUrl.replace(/\/$/, "")}/v1/llm/config`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ llm_api_base: settings.llmApiUrl, llm_api_key: settings.llmApiKey, llm_model: settings.llmModel }),
                    }).catch(() => {});
                    flash("设置已保存");
                  }}><Icon name="check"/>保存设置</button></div>
              <details className="security-note"><summary>安全提示</summary><p>建议只允许本机访问这些服务。如果从另一台电脑打开本页面，浏览器可能无法连接这台电脑上的本地服务。</p></details>
            </section>
          </div>
        )}
      </section>
      {notice && <div className="toast"><Icon name="check" size={18}/>{notice}</div>}
    </main>
  );
}

function PageTitle({ kicker, title, description }: { kicker: string; title: string; description: string }) {
  return <div className="page-title"><div className="eyebrow"><span/>{kicker}</div><h1>{title}</h1><p>{description}</p></div>;
}

function PanelHeading({ number, title, text }: { number: string; title: string; text: string }) {
  return <div className="panel-heading"><span>{number}</span><div><h2>{title}</h2><p>{text}</p></div></div>;
}

function ResourceBar({ label, value, width }: { label: string; value: string; width: string }) {
  return <div className="resource-bar"><div><span>{label}</span><b>{value}</b></div><i><em style={{ width }}/></i></div>;
}

function SpaceControl({ label, value, min, max, step, unit, onChange }: { label: string; value: number; min: number; max: number; step: number; unit: string; onChange: (value: number) => void }) {
  const percentage = ((value - min) / (max - min)) * 100;
  return <label className="space-control"><span><b>{label}</b><output>{Number.isInteger(step) ? value.toFixed(0) : value.toFixed(step < 0.1 ? 2 : 1)} {unit}</output></span><input type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} style={{ "--range": `${percentage}%` } as React.CSSProperties}/></label>;
}
