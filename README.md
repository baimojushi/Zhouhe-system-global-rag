# 全局 RAG 检索工作台

连接 Weaviate、BGE-M3、RAG Gateway 与 vLLM 的本地 GUI。

完整安装、Docker、API 和 CORS 说明见 [README_LOCAL_DEPLOY.md](README_LOCAL_DEPLOY.md)。
固定依赖版本见 [DEPENDENCY_MANIFEST.md](DEPENDENCY_MANIFEST.md)。

快速启动：

```bash
npm ci
npm run build
npm start
```

然后打开 <http://127.0.0.1:3000>。服务启动后可在另一个终端运行
`npm run verify:ui`，同时验证主页和产品样式资源是否正常。

顶部工具栏可切换“深空模式”。背景来自 ESO 帕拉纳尔 ALPACA 全天空相机的实际科学观测帧；Docker sidecar 每小时检查更新，当地白天或质量不合格时明确显示“最近可用夜空”。默认不叠加合成星，用户可选择开启带可调视星等和微弱闪烁的氛围增强层。实现与数据字段见 [REALTIME_SKY_BACKGROUND.md](REALTIME_SKY_BACKGROUND.md)，资产来源见 [THIRD_PARTY_ASSETS.md](THIRD_PARTY_ASSETS.md)。

知识库页面已升级为多级目录工作台，内置 AI 工作记录、学术资料、生产文档、个人思维笔记和关联知识库。闭源 AI 归类采用“手动大类 → 未归类 → 点击生成提案 → 人工确认”的流程，后端与 Token 预算见 [BACKEND_KNOWLEDGE_ITERATION_PLAN.md](BACKEND_KNOWLEDGE_ITERATION_PLAN.md)。
