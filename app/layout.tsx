import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "全局 RAG 检索工作台",
  description: "连接 Weaviate、内置 BGE-M3 与 llama.cpp Gemma 的本地混合检索界面。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
