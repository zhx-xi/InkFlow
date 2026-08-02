# frontend/ — 前端（预留）

本目录是 InkFlow 前端代码的落盘位置（0.3.0 起启用）。

## 定位（ADR-020，Issue #65 产品形态拍板）

- **一套两用**：本地 GUI（Electron 壳）与云端 Web（2.0.0）共享同一 React 代码、组件库与 API client
- **技术栈**：React 19 + Vite 6 + shadcn/ui + Zustand 5 + Tailwind 4（ADR-020）
- **通信**：GUI 渲染进程 ↔ 本地内核 = REST + SSE（ADR-021），不承载业务逻辑
- **依赖锁定**：提交 `pnpm-lock.yaml`（ADR-025），CI 用 `pnpm install --frozen-lockfile`

## 里程碑

| 版本 | 内容 |
|------|------|
| 0.3.0 | F19 GUI（Electron 壳 + 内核进程化）· F23 SSE 流式（提前） |
| 2.0.0 | F18 云 Web（云端专属界面，本地界面由 GUI 承接） |

> 目录名曾为 `ui/`（ADR-018 早期预留名），2026-08-02 结构同步时重命名为 `frontend/` 与 `backend/` 对称。
