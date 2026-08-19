/**
 * 设置页「知识图谱提取」卡片 RED 契约测试（#479 前端，specs/f48-knowledge-graph/spec.md §5.5.7）。
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【契约（父侧定稿，2026-08-19）——docstring 逐字声明，GREEN 照做转绿】
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 1) 新组件 components/knowledge-graph/KnowledgeExtractCard.tsx（GREEN CREATE），
 *    挂载于设置页常规分类（settings.tsx GeneralPanel 内，GREEN 只挂载不内联）：
 *    - 启用开关（Switch，data-testid='kg-extract-enabled'）
 *    - 提取频率 Select（data-testid='kg-extract-interval'，选项 1/6/12/24/72/168 小时）
 *    - 提取方式 Radio 三选项（容器 data-testid='kg-extract-method'；值 rule/ai/both，
 *      选项可访问名 = 选项文案「仅规则 / 仅 AI / 规则+AI」，i18n settings.kgExtract.rule/ai/both）
 *    - 立即运行按钮（data-testid='kg-extract-run-now'）
 *    - 卡片区域根容器 data-testid='kg-extract-card'（「设置页渲染出知识图谱提取卡片区域」锚点）
 *    - AI 选项（ai/both）disabled 语义 = 原生 disabled 或 aria-disabled（jest-dom toBeDisabled
 *      对两者均匹配；自研 div role=radio 方案必须带 aria-disabled=true 才算满足契约）
 *    - 频率选项 label 形态 = 「N 小时」（可访问名含数字+小时，测试按文案字面量断言防键空洞）
 *
 * 2) 设置读写：GET/PATCH /api/v1/settings 三键
 *    kg_extract_enabled / kg_extract_interval_hours / kg_extract_method
 *    （测试 mock fetch：fetchSettings/patchSettings 走 vi.hoisted 假实现（client.ts 模块
 *    作用域闭包坑——只 mock apiFetch 时真实 patchSettings 会打网络），apiFetch 走 URL 分发；
 *    断言「PATCH body 含三键形态」用双通道收集 helper：patchSettingsMock.calls ∪
 *    apiFetchMock PATCH /api/v1/settings 的 body，任一通道命中即契约成立）
 *
 * 3) 未配模型门禁（核心用例，D3 拍板）：
 *    - hasChatModel=false（providers 空或无 key_saved）→ AI 选项（ai/both）disabled +
 *      提示文案出现（getByText 匹配 i18n settings.kgExtract.needModel 对应中文文案
 *      「需先在模型设置中配置大模型」——测试断言中文文案字面量，防 i18n 键空洞）
 *    - hasChatModel=true → AI 选项可用 + 提示文案不出现
 *    - 播种与 mock 双处同源（#474 教训）：未配置用例 setState({providers:[]}) +
 *      apiFetchMock provider-configs → 空列表；已配置用例 setState(READY_PROVIDER) +
 *      provider-configs → 同款（防 GREEN 懒加载 loadProviders 拉回覆盖播种）
 *
 * 4) 立即运行：点击 → POST /api/v1/knowledge/extract（mock 200 + ExtractionResult 形态
 *    {type:'knowledge_relation',status,created,updated,warnings,model}）→ 运行中按钮 disabled
 *    （GET /api/v1/knowledge/extract/status running=true 轮询语义：POST 后置 running=true，
 *    按钮 disabled + loading；置 false 后下一轮询恢复 enabled——mock 一次 running=true 再 false）
 *
 * 5) i18n：settings.kgExtract.* 键 zh/en 均存在（断言 zh.ts/en.ts 对象结构，
 *    RED 期失败形态 = undefined）。契约键集：title/enabled/interval/method/rule/ai/both/
 *    needModel/runNow/running（中文文案：title=知识图谱提取、needModel=需先在模型设置中配置大模型、
 *    runNow=立即运行，其余键 GREEN 自由定文案但键必须存在）
 *
 * ───────────────────────────────────────────────────────────────────────────
 * 【RED 预期失败形态】
 * ① element-missing：kg-extract-* testid 不存在（KnowledgeExtractCard 未建/未挂载，
 *    或 GREEN 挂错分类）——本文件绝大部分用例
 * ② i18n 键 undefined：zh/en 的 settings.kgExtract.* 为 undefined（assert 类）
 * ③ 守护用例（主题设置渲染）当前 PASS 刻意——确认既有区域零回归
 * 注：本文件不 import 任何新 api 客户端函数（契约 2/4 经 apiFetch mock + URL 断言），
 *    规避「测试 import 未建模块 → 文件级 0 用例连坐」；module-not-found 形态不出现。
 *
 * 【GREEN 换算清单】components/knowledge-graph/KnowledgeExtractCard.tsx（CREATE）+
 * settings.tsx GeneralPanel 挂载 + i18n zh/en settings.kgExtract.* 键 + 无新 api 函数
 * （设置读写复用 client.ts fetchSettings/patchSettings；extract/status 走 apiFetch 直调
 *  POST /api/v1/knowledge/extract、GET /api/v1/knowledge/extract/status）。
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SettingsPage } from './settings';
import { apiFetch } from '../api/client';
import { useModelsStore, type ProviderConfig } from '../stores/models';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import { zh } from '../i18n/zh';
import { en } from '../i18n/en';

// client.ts 模块内函数（fetchSettings/patchSettings）经 importOriginal 展开后函数体仍引用
// 真实 apiFetch（模块作用域闭包）→ 只 mock apiFetch 时真实 patchSettings 会打网络 → 必须
// vi.hoisted 直接替换（2026-08-08 父侧裁定，settings.test.tsx 同款）
const { fetchSettingsMock, patchSettingsMock } = vi.hoisted(() => ({
  fetchSettingsMock: vi.fn(),
  patchSettingsMock: vi.fn(),
}));

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    apiFetch: vi.fn(),
    fetchSettings: fetchSettingsMock,
    patchSettings: patchSettingsMock,
  };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 默认设置对象（F32 全量 + #479 三键默认值：enabled=false / interval=24 / method=rule，spec §5.5.2） */
const DEFAULT_SETTINGS = {
  theme: 'paper',
  bg: 'default',
  lang: 'zh',
  font: 'sans',
  close_behavior: 'tray',
  tray_hint_dismissed: false,
  default_words: 800000,
  kg_extract_enabled: false,
  kg_extract_interval_hours: 24,
  kg_extract_method: 'rule',
};

/** 已配置 chat 模型 provider（hasChatModel=true 判定样本；全字段镜像 ProviderConfig 接口防 TS2322） */
const READY_PROVIDER: ProviderConfig = {
  id: 1,
  name: 'deepseek',
  base_url: 'https://api.deepseek.com',
  default_model: 'deepseek-chat',
  models: [{ id: 'deepseek-chat', type: 'chat', roles: [] }],
  key_saved: true,
  max_retries: 3,
  timeout: 60,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

/** POST /knowledge/extract 的 200 响应（ExtractionResult 信封形态，spec §5.5.6 同 POST /extract） */
const EXTRACTION_RESULT = {
  type: 'knowledge_relation',
  status: 'completed',
  created: 3,
  updated: 0,
  warnings: [] as string[],
  model: null,
};

/** i18n 契约键集（settings.kgExtract.*，zh/en 双断言；RED 期 undefined） */
const KG_EXTRACT_KEYS = [
  'title',
  'enabled',
  'interval',
  'method',
  'rule',
  'ai',
  'both',
  'needModel',
  'runNow',
  'running',
] as const;

/** 双通道收集「PATCH /api/v1/settings 的 body」（patchSettingsMock ∪ apiFetchMock），GREEN 走任一通道均可转绿 */
function collectSettingsPatchBodies(): Array<Record<string, unknown>> {
  const bodies: Array<Record<string, unknown>> = [];
  for (const args of patchSettingsMock.mock.calls) {
    if (args[0] && typeof args[0] === 'object') bodies.push(args[0] as Record<string, unknown>);
  }
  for (const [path, init] of apiFetchMock.mock.calls) {
    if (path === '/api/v1/settings' && (init as { method?: string } | undefined)?.method === 'PATCH') {
      const body = (init as { body?: unknown }).body;
      if (body && typeof body === 'object') bodies.push(body as Record<string, unknown>);
    }
  }
  return bodies;
}

function renderSettings(initialPath = '/settings') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <SettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  patchSettingsMock.mockReset();
  patchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS });
  fetchSettingsMock.mockReset();
  fetchSettingsMock.mockResolvedValue({ ...DEFAULT_SETTINGS });
  // 扩展重置：models/project/theme/toast 播种默认（测试间隔离，防「上一用例改 store → 下一用例初值漂移」）
  useModelsStore.setState({ providers: [], loading: false, error: null });
  useProjectStore.setState({
    projects: [{ id: 'p1', name: '青云志', genre: '玄幻', language: 'zh-CN', target_words: 800000, config: {}, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z' }],
    currentProjectId: 'p1', loading: false, error: null,
  });
  useThemeStore.setState({
    theme: 'paper', bg: 'default', lang: 'zh', font: 'sans', closeBehavior: 'tray', trayHintDismissed: false,
  } as unknown as Partial<ReturnType<typeof useThemeStore.getState>>);
  useToastStore.setState({ toasts: [] });
  // URL 分发默认 mock：#479 卡片（GREEN 后）挂载会 GET settings（fetchSettingsMock 已接管，
  // 此处兜底 apiFetch 直调形态）+ 可能 GET extract/status；未配模型用例 provider-configs → 空
  apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path === '/api/v1/settings') {
      if (init?.method === 'PATCH') return { ...DEFAULT_SETTINGS, ...((init as { body?: object }).body ?? {}) };
      return { ...DEFAULT_SETTINGS };
    }
    if (path === '/api/v1/knowledge/extract/status') return { running: false, last_run: null };
    if (path === '/api/v1/knowledge/extract' && init?.method === 'POST') return { ...EXTRACTION_RESULT };
    if (path === '/api/v1/provider-configs') return { items: [], total: 0, offset: 0, limit: 50 };
    return { ok: true };
  });
});

describe('设置页 — 知识图谱提取卡片（#479，spec §5.5.7）', () => {
  it('守护（确认型）：设置页常规分类既有区域正常渲染——主题 radio「素笺」+ settings-page（RED 期 PASS 刻意）', () => {
    renderSettings();
    expect(screen.getByTestId('settings-page')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /素笺/ })).toBeInTheDocument();
  });

  it('契约1a：设置页渲染出知识图谱提取卡片区域（kg-extract-card 根容器 + 标题「知识图谱提取」）', () => {
    renderSettings();
    // RED：KnowledgeExtractCard 未建/未挂载 → Unable to find element by [data-testid="kg-extract-card"]
    const card = screen.getByTestId('kg-extract-card');
    expect(within(card).getByText('知识图谱提取')).toBeInTheDocument();
  });

  it('契约1b：四控件齐全——启用开关 / 频率 Select / 方式 Radio 组 / 立即运行按钮', () => {
    renderSettings();
    const card = screen.getByTestId('kg-extract-card');
    expect(within(card).getByTestId('kg-extract-enabled')).toBeInTheDocument();
    expect(within(card).getByTestId('kg-extract-interval')).toBeInTheDocument();
    expect(within(card).getByTestId('kg-extract-method')).toBeInTheDocument();
    expect(within(card).getByTestId('kg-extract-run-now')).toBeInTheDocument();
    // 三方式选项齐全：仅规则 / 仅 AI / 规则+AI（i18n settings.kgExtract.rule/ai/both 文案字面量）
    expect(within(card).getByRole('radio', { name: '仅规则' })).toBeInTheDocument();
    expect(within(card).getByRole('radio', { name: '仅 AI' })).toBeInTheDocument();
    expect(within(card).getByRole('radio', { name: '规则+AI' })).toBeInTheDocument();
  });

  it('契约1c：提取频率选项 = 1/6/12/24/72/168 小时（Select 展开 → 六选项）', async () => {
    const user = userEvent.setup();
    renderSettings();
    const trigger = screen.getByTestId('kg-extract-interval');
    await user.click(trigger);
    // Radix Select 选项 portal 到 body → screen 级查询（jsdom + Radix 已由 setup.ts 兜底）
    for (const h of ['1 小时', '6 小时', '12 小时', '24 小时', '72 小时', '168 小时']) {
      expect(await screen.findByRole('option', { name: h })).toBeInTheDocument();
    }
  });

  it('契约2a：设置回显——GET settings 三键（enabled=true / interval=72 / method=ai）驱动控件初值', async () => {
    fetchSettingsMock.mockResolvedValueOnce({ ...DEFAULT_SETTINGS, kg_extract_enabled: true, kg_extract_interval_hours: 72, kg_extract_method: 'ai' });
    renderSettings();
    const card = screen.getByTestId('kg-extract-card');
    await waitFor(() => {
      expect(within(card).getByTestId('kg-extract-enabled')).toBeChecked();
    });
    expect(within(card).getByTestId('kg-extract-interval')).toHaveTextContent('72 小时');
    expect(within(card).getByRole('radio', { name: '仅 AI' })).toBeChecked();
  });

  it('契约2b：切换启用开关 → PATCH body 含 kg_extract_enabled（三键形态之一）', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(await screen.findByTestId('kg-extract-enabled'));
    await waitFor(() => {
      expect(collectSettingsPatchBodies().some((b) => b.kg_extract_enabled === true)).toBe(true);
    });
  });

  it('契约2c：切换提取频率 → PATCH body 含 kg_extract_interval_hours', async () => {
    const user = userEvent.setup();
    renderSettings();
    await user.click(await screen.findByTestId('kg-extract-interval'));
    await user.click(await screen.findByRole('option', { name: '72 小时' }));
    await waitFor(() => {
      expect(collectSettingsPatchBodies().some((b) => b.kg_extract_interval_hours === 72)).toBe(true);
    });
  });

  it('契约2d：切换提取方式 → PATCH body 含 kg_extract_method（已配模型前置）', async () => {
    useModelsStore.setState({ providers: [READY_PROVIDER] });
    const user = userEvent.setup();
    renderSettings();
    await user.click(await screen.findByRole('radio', { name: '仅 AI' }));
    await waitFor(() => {
      expect(collectSettingsPatchBodies().some((b) => b.kg_extract_method === 'ai')).toBe(true);
    });
  });

  it('契约3a（核心门禁）：未配模型（providers 空）→ AI 选项（ai/both）disabled + 提示「需先在模型设置中配置大模型」', () => {
    // 未配置用例：播种 + mock 双处同源（#474）——beforeEach 已 setState({providers:[]}) + provider-configs → 空
    renderSettings();
    const card = screen.getByTestId('kg-extract-card');
    expect(within(card).getByRole('radio', { name: '仅规则' })).toBeEnabled();
    expect(within(card).getByRole('radio', { name: '仅 AI' })).toBeDisabled();
    expect(within(card).getByRole('radio', { name: '规则+AI' })).toBeDisabled();
    // 中文文案字面量断言（防 i18n 键空洞：settings.kgExtract.needModel）
    expect(screen.getByText('需先在模型设置中配置大模型')).toBeInTheDocument();
  });

  it('契约3b（核心门禁）：已配 chat 模型（key_saved=true）→ AI 选项可用 + 提示文案不出现', () => {
    // 已配置用例：播种 + mock 双处同源（#474）——provider-configs mock 返回同款 READY_PROVIDER
    useModelsStore.setState({ providers: [READY_PROVIDER] });
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/provider-configs') return { items: [READY_PROVIDER], total: 1, offset: 0, limit: 50 };
      if (path === '/api/v1/settings') return { ...DEFAULT_SETTINGS };
      if (path === '/api/v1/knowledge/extract/status') return { running: false, last_run: null };
      return { ok: true };
    });
    renderSettings();
    const card = screen.getByTestId('kg-extract-card');
    expect(within(card).getByRole('radio', { name: '仅 AI' })).toBeEnabled();
    expect(within(card).getByRole('radio', { name: '规则+AI' })).toBeEnabled();
    expect(screen.queryByText('需先在模型设置中配置大模型')).not.toBeInTheDocument();
  });

  it('契约4：立即运行 → POST /api/v1/knowledge/extract + 运行中按钮 disabled（status 轮询 running=true → false 恢复）', async () => {
    // 状态化 mock：POST 后置 running=true（按钮 disabled），用例内置 false → 下一轮询恢复 enabled
    let statusRunning = false;
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/knowledge/extract' && init?.method === 'POST') {
        statusRunning = true;
        return { ...EXTRACTION_RESULT };
      }
      if (path === '/api/v1/knowledge/extract/status') return { running: statusRunning, last_run: null };
      if (path === '/api/v1/settings') return { ...DEFAULT_SETTINGS };
      if (path === '/api/v1/provider-configs') return { items: [], total: 0, offset: 0, limit: 50 };
      return { ok: true };
    });
    const user = userEvent.setup();
    renderSettings();
    const runBtn = await screen.findByTestId('kg-extract-run-now');
    expect(runBtn).toBeEnabled();
    await user.click(runBtn);
    // POST /api/v1/knowledge/extract 发出（宽容端点断言）
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.some((c) => c[0] === '/api/v1/knowledge/extract' && (c[1] as { method?: string } | undefined)?.method === 'POST')).toBe(true);
    });
    // 运行中：status running=true → 按钮 disabled
    await waitFor(() => expect(runBtn).toBeDisabled(), { timeout: 3000 });
    // 完成：置 running=false → 轮询恢复 → 按钮 enabled（mock 一次 running=true 再 false）
    statusRunning = false;
    await waitFor(() => expect(runBtn).toBeEnabled(), { timeout: 3000 });
    // 轮询语义实证：status 端点至少被轮询 2 次
    expect(apiFetchMock.mock.calls.filter((c) => c[0] === '/api/v1/knowledge/extract/status').length).toBeGreaterThanOrEqual(2);
  });

  it('契约5：i18n settings.kgExtract.* 键 zh/en 均存在（RED 期 undefined 失败形态）', () => {
    for (const k of KG_EXTRACT_KEYS) {
      const key = `settings.kgExtract.${k}` as const;
      // RED：键不存在 → zh[key] === undefined → toBeTruthy FAIL（assert 类）
      expect(zh[key as keyof typeof zh]).toBeTruthy();
      expect(en[key]).toBeTruthy();
    }
    // 核心文案防空洞：needModel 中文文案字面量钉死（与契约3a getByText 断言同源）
    expect(zh['settings.kgExtract.needModel' as keyof typeof zh]).toBe('需先在模型设置中配置大模型');
  });
});
