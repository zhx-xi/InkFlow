/**
 * NewProjectDialog 测试契约（Issue #105 §6.2③ 模态交互 + §6.3② 创建失败错误展示）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 src/components/NewProjectDialog.tsx 必须匹配：
 *
 * §6.2③ 模态交互（新增）：
 * - ESC 键关闭：keydown Escape（焦点在对话框内时）→ 调用 onClose、对话框卸载
 * - 遮罩点击关闭：点击 backdrop（role=dialog 的外层容器）→ onClose（dialog 内部点击不冒泡关闭）
 * - 焦点归还：任何关闭路径（ESC/遮罩/取消）后焦点归还触发按钮（记录打开时 activeElement
 *   或调用方传 triggerRef；本测试用 Harness 模拟 projects.tsx 的「触发按钮打开对话框」用法）
 * - 过渡动效（≤180ms，reduced-motion 降级）：不测样式，仅要求关闭可同步/短时完成（waitFor 兜底）
 *
 * §6.3② 创建失败错误展示（新增，现状 handleCreate 无 try/catch）：
 * - createProject reject → 对话框内展示错误文案（复用现有内联 error 区域，样式 text-err）
 * - 新增 i18n key：`dlg.createFailed`（如「创建失败: {原因}」）——GREEN 补 zh.ts/en.ts
 * - 对话框保持打开（用户可修正后重试）
 *
 * 既有行为保持（迁移自 projects.test.tsx）：
 * - 创建成功 → POST /api/v1/projects（body {name, tags, language, target_words}）→ navigate('/writing')
 * - 书名空校验「书名不能为空」不发 POST（既有）
 *
 * ⚠️ #105 修复批契约（评审 findings 驱动，2026-08-06）：
 * - submitting 状态防双重提交：createProject in-flight 时「创建」按钮 disabled（aria-busy 可叠加，
 *   但必须 disabled——否则用户仍可连点），双击/连点 → POST /api/v1/projects 仅 1 次
 * - in-flight 时 ESC：关闭路径忽略——对话框保持打开（契约选「不关闭」方案；若实现选
 *   「关闭但不 navigate」需同步改本断言）
 * - ESC 与 Radix Select 交互：题材/语言下拉打开时按 ESC → 仅关闭下拉面板（option 消失），
 *   对话框保留（Radix DismissableLayer 在 document capture 阶段对 Escape preventDefault →
 *   对话框 ESC 监听必须尊重 e.defaultPrevented，不得误关）
 *
 * RED 预期：ESC 关闭/焦点归还/错误展示缺失 → element-missing / 行为断言 FAIL。
 *
 * ⚠️ #107 Agent 模板下拉 RED 契约（2026-08-06，spec §9.2.5 / §9.5 / M5）：
 * - 对话框内新增「Agent 模板」下拉（Radix Select，combobox aria-label「Agent 模板」，
 *   新 i18n key：dlg.template='Agent 模板' dlg.templateDefault='默认模板'）：
 *   选项 = 「默认模板」+ useTemplatesStore.templates 名称列表；默认选中「默认模板」（无模板）
 * - 选择已建模板 → createProject body 携带 template_id（项目建立模板引用，创建即引用）；
 *   选择「默认模板」→ body 不含 template_id
 * - 模板数据源 = useTemplatesStore（GREEN 可在挂载时 loadTemplates，幂等守卫允许；
 *   测试 seed store + mock GET 双兼容）
 * - RED 阶段 mock：vi.mock('../stores/templates')（GREEN 才创建；测试内假 store 提供种子数据）→
 *   本文件 RED 形态 = 新用例 element-missing（combobox「Agent 模板」不存在），既有用例保持绿。
 */
import { useState } from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { NewProjectDialog } from './NewProjectDialog';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

// ⚠️ #107 RED 阶段 mock：stores/templates 由 GREEN 创建，本文件以测试内假 store 提供
// （loadTemplates 为 no-op——对话框用例只依赖 beforeEach 种子数据；其他 action 面板
// 不需要，no-op 兜底防 GREEN 挂载调用缺失 action 崩溃）。GREEN 落地后此 mock 可删，
// 改真实 import。真实 store 行为契约见 stores/templates.test.ts。
const templatesStoreRef = vi.hoisted(() => ({ store: null as unknown }));
vi.mock('../stores/templates', async () => {
  const { create } = await import('zustand');
  const useTemplatesStore = create<{
    templates: unknown[];
    loading: boolean;
    error: string | null;
    defaultTemplateId: number | null;
    loadTemplates: () => Promise<void>;
    createTemplate: () => Promise<unknown>;
    updateTemplate: () => Promise<unknown>;
    deleteTemplate: () => Promise<void>;
    duplicateTemplate: () => Promise<unknown>;
    setDefault: () => Promise<void>;
    loadDefault: () => Promise<void>;
  }>(() => ({
    templates: [],
    loading: false,
    error: null,
    defaultTemplateId: null,
    loadTemplates: async () => {},
    createTemplate: async () => ({}),
    updateTemplate: async () => ({}),
    deleteTemplate: async () => {},
    duplicateTemplate: async () => ({}),
    setDefault: async () => {},
    loadDefault: async () => {},
  }));
  templatesStoreRef.store = useTemplatesStore;
  return { useTemplatesStore };
});

const apiFetchMock = vi.mocked(apiFetch);

/** 模拟 projects.tsx 用法：触发按钮打开对话框（焦点归还的目标） */
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" data-testid="open-trigger" onClick={() => setOpen(true)}>
        打开新建
      </button>
      {open && <NewProjectDialog onClose={() => setOpen(false)} />}
    </div>
  );
}

function renderHarness() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Harness />} />
        <Route path="/writing" element={<div data-testid="writing-probe">写作页探针</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useProjectStore.setState({
    projects: [],
    currentProjectId: null,
    loading: false,
    error: null,
    chapterProgress: {},
  });
  // #107 兼容：GREEN 对话框挂载时可能 loadTemplates（GET /api/v1/agent-templates），
  // 路径感知 mock 防止既有用例被空列表覆盖 / {ok:true} 响应误解析
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/agent-templates') return { items: [], total: 0, offset: 0, limit: 50 };
    return { ok: true };
  });
  // RED 阶段假 store 工厂尚未运行（对话框尚未 import 模板 store）→ 空安全重置；
  // GREEN 落地后工厂随 import 执行，store 引用就位，种子生效
  (templatesStoreRef.store as { setState: (partial: unknown) => void } | null)?.setState({
    templates: [],
    loading: false,
    error: null,
    defaultTemplateId: null,
  });
});

/** #107 模板下拉种子数据（与 stores/templates 契约一致的 AgentTemplate 形状） */
interface DialogTemplate {
  id: number;
  name: string;
  description: string;
  main_model: string;
  default_temperature: number;
  roles: {
    architect: { model: string | null; temperature: number | null; enabled: boolean };
    writer: { model: string | null; temperature: number | null; enabled: boolean };
    auditor: { model: string | null; temperature: number | null; enabled: boolean };
    reviser: { model: string | null; temperature: number | null; enabled: boolean };
  };
  default_words: number;
  is_default: boolean;
  used_by?: Array<{ id: string; name: string }>;
  created_at: string;
  updated_at: string;
}

const DIALOG_TEMPLATES: DialogTemplate[] = [
  {
    id: 1,
    name: '经典玄幻',
    description: '标准玄幻创作模板',
    main_model: 'gpt-4o',
    default_temperature: 0.7,
    roles: {
      architect: { model: 'deepseek-chat', temperature: 0.4, enabled: true },
      writer: { model: 'gpt-4o', temperature: 0.8, enabled: true },
      auditor: { model: 'gpt-4o', temperature: 0.5, enabled: true },
      reviser: { model: 'deepseek-chat', temperature: 0.6, enabled: true },
    },
    default_words: 800000,
    is_default: true,
    used_by: [{ id: 'p1', name: '青云志' }],
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  },
  {
    id: 2,
    name: '悬疑推理',
    description: '悬疑推理创作模板',
    main_model: 'deepseek-chat',
    default_temperature: 0.6,
    roles: {
      architect: { model: null, temperature: null, enabled: true },
      writer: { model: 'deepseek-chat', temperature: 0.9, enabled: true },
      auditor: { model: null, temperature: null, enabled: true },
      reviser: { model: null, temperature: null, enabled: true },
    },
    default_words: 600000,
    is_default: false,
    used_by: [],
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  },
];

/** 种子测试内假模板 store（下拉选项数据源；loadTemplates 为 no-op 不覆盖） */
function seedTemplatesStore(templates: DialogTemplate[]) {
  (templatesStoreRef.store as { setState: (partial: unknown) => void } | null)?.setState({
    templates,
    loading: false,
    error: null,
  });
}

describe('新建项目对话框 — ESC 关闭 + 遮罩点击 + 焦点归还（Issue #105 §6.2③）', () => {
  it('ESC 键关闭对话框 + 焦点归还触发按钮', async () => {
    const user = userEvent.setup();
    renderHarness();

    const trigger = screen.getByTestId('open-trigger');
    await user.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // 焦点在对话框内时按 ESC → 关闭 + 焦点回到触发按钮
    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(document.activeElement).toBe(trigger);
  });

  // ⚠️ #195 契约升级（2026-08-08 用户拍板）：遮罩点击**不再关闭**对话框——rc3 复验发现
  // 「鼠标移到外面自动关闭」导致输入内容丢失（误触）；关闭路径仅：取消按钮 / ESC / 创建成功。
  it('遮罩点击不关闭：#195 防误触（点击 backdrop → 对话框保持；dialog 内部点击也不关闭）', async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    const dialog = screen.getByRole('dialog');
    // backdrop = role=dialog 的外层容器（presentation 角色不在可访问性树，用 DOM 查询）
    const backdrop = dialog.parentElement as HTMLElement;
    expect(backdrop).not.toBeNull();

    // dialog 内部点击（如标题区域）不关闭
    fireEvent.click(dialog);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // 遮罩点击 → #195 不再关闭（防误触；创建成功/取消/ESC 才关闭）
    fireEvent.click(backdrop);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  // ⚠️ #195 契约（2026-08-08）：目标字数清空可重输——rc3 复验「改不了」根因 =
  // type="number" + Number('')=0 → 清空瞬间变 0，无法重输。契约：清空 → 输入框显示空字符串。
  it('目标字数清空重输：#195 清空输入框 → 显示空（不强制变 0），可输入新值', async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    const input = screen.getByLabelText('目标字数') as HTMLInputElement;
    expect(input.value).toBe('800000'); // 默认值（既有契约）
    await user.clear(input);
    expect(input.value).toBe(''); // #195：清空后为空（当前实现 Number('')=0 → 变 '0' → FAIL）
    await user.type(input, '1500');
    expect(input.value).toBe('1500');
  });

  it('取消按钮关闭 + 焦点归还触发按钮', async () => {
    const user = userEvent.setup();
    renderHarness();

    const trigger = screen.getByTestId('open-trigger');
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: '取消' }));

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    expect(document.activeElement).toBe(trigger);
  });
});

describe('新建项目对话框 — 创建失败错误展示（Issue #105 §6.3②）', () => {
  it('createProject 失败 → 内联错误文案展示 + 对话框保持打开', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核未就绪'));
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');

    // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));

    await user.click(screen.getByRole('button', { name: '创建' }));

    // GREEN 契约：新 i18n key `dlg.createFailed`（如「创建失败: 内核未就绪」）内联展示
    expect(await screen.findByText(/创建失败/)).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });

  it('书名空校验保持：空书名 → 「书名不能为空」，不发 POST', async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.click(screen.getByRole('button', { name: '创建' }));

    expect(screen.getByText('书名不能为空')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });
});

describe('新建项目对话框 — 书名长度校验（spec N2）', () => {
  it('书名超过 100 字 → 「书名不能超过 100 字」，不发 POST', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByTestId('open-trigger'));
    const nameInput = within(screen.getByRole('dialog')).getByLabelText('书名');
    await user.type(nameInput, 'x'.repeat(101));
    await user.click(screen.getByRole('button', { name: '创建' }));
    expect(screen.getByText('书名不能超过 100 字')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });
});

describe('新建项目对话框 — 提交中状态与 ESC 交互（#105 修复批契约）', () => {
  const createdProject = {
    id: 'p9',
    name: '青山入我怀',
    tags: ['玄幻'],
    language: 'zh-CN',
    target_words: 800000,
    config: {},
    created_at: '2026-08-06T10:00:00Z',
    updated_at: '2026-08-06T10:00:00Z',
  };

  /** createProject 挂起：POST 返回手动控制的 pending promise（模拟 in-flight 请求）；返回 finish() 收尾 */
  function mockPendingCreate() {
    let resolveCreate!: (v: unknown) => void;
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') {
        return new Promise((resolve) => {
          resolveCreate = resolve;
        });
      }
      return { ok: true };
    });
    return () => resolveCreate(createdProject);
  }

  it('提交中防双重提交：双击「创建」→ POST 仅 1 次 + 按钮 disabled', async () => {
    const finish = mockPendingCreate();
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');

    // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));

    const createBtn = screen.getByRole('button', { name: '创建' });
    await user.click(createBtn);
    // 第一击后立即第二击（双击场景；RED：无 submitting 保护 → 并发两次 POST + 按钮未禁用）
    await user.click(createBtn);

    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(createBtn).toBeDisabled();

    finish();
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });

  it('提交中按 ESC：对话框保持打开（in-flight 关闭路径忽略，防误关丢进度）', async () => {
    const finish = mockPendingCreate();
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');
    // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));
    await user.click(screen.getByRole('button', { name: '创建' }));

    // in-flight 中按 ESC（RED：当前实现直接 onClose → 对话框卸载，本断言失败）
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // 请求完成后照常跳转写作页
    finish();
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });

  it('tags 多选打开时按 ESC：仅关闭下拉面板，对话框保留', async () => {
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    // 打开 tags 多选（Radix Select，trigger testid=tags-select）
    await user.click(screen.getByTestId('tags-select'));
    expect(await screen.findByRole('option', { name: '玄幻' })).toBeInTheDocument();

    // 按 ESC：Radix 面板关闭（capture 阶段 preventDefault → 对话框 ESC 监听应跳过，不得误关）
    await user.keyboard('{Escape}');
    await waitFor(() => {
      expect(screen.queryByRole('option', { name: '玄幻' })).not.toBeInTheDocument();
    });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe('新建项目对话框 — 创建成功（既有行为保持）', () => {
  it('创建成功：POST /api/v1/projects → 201 → 跳转写作页', async () => {
    const created = {
      id: 'p9',
      name: '青山入我怀',
      tags: ['玄幻'],
      language: 'zh-CN',
      target_words: 800000,
      config: {},
      created_at: '2026-08-06T10:00:00Z',
      updated_at: '2026-08-06T10:00:00Z',
    };
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return created;
      return { ok: true };
    });
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');

    // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));

    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', tags: ['玄幻'], language: 'zh-CN', target_words: 800000 },
      });
    });
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });

  // #595 契约（2026-08-23）：创建须 ≥1 个题材/标签（题材为空 → 显示错误 + 不调 POST）
  it('未选择题材/标签 → 显示错误「请至少选择一个题材/标签」+ 不调 POST', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');
    await user.click(screen.getByRole('button', { name: '创建' }));
    expect(await screen.findByText('请至少选择一个题材/标签')).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ method: 'POST' }));
  });
});

/**
 * #107 Agent 模板下拉（2026-08-06，spec §9.2.5 / §9.5 / M5）。
 * RED 预期：GREEN 前对话框无模板下拉 → 本 describe 全部 element-missing
 * （combobox「Agent 模板」不存在）；既有用例保持绿。
 */
describe('新建项目对话框 — Agent 模板下拉（#107 RED 契约）', () => {
  beforeEach(() => {
    seedTemplatesStore(DIALOG_TEMPLATES);
  });

  it('下拉显示「默认模板」+ 已建模板列表；默认选中「默认模板」', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByTestId('open-trigger'));

    const select = screen.getByRole('combobox', { name: 'Agent 模板' });
    expect(select).toHaveTextContent('默认模板');
    await user.click(select);
    expect(await screen.findByRole('option', { name: '默认模板' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '经典玄幻' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '悬疑推理' })).toBeInTheDocument();
  });

  it('选择已建模板 → createProject body 携带 template_id（建立模板引用）', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');

    // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));

    await user.click(screen.getByRole('combobox', { name: 'Agent 模板' }));
    await user.click(await screen.findByRole('option', { name: '悬疑推理' }));
    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, template_id: 2 },
      });
    });
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });

  it('选择「默认模板」→ createProject body 不含 template_id', async () => {
    const user = userEvent.setup();
    renderHarness();
    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');

    // #595 契约：创建须 ≥1 个题材/标签（tags 多选勾选预设标签）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));

    await user.click(screen.getByRole('combobox', { name: 'Agent 模板' }));
    await user.click(await screen.findByRole('option', { name: '默认模板' }));
    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', tags: ['玄幻'], language: 'zh-CN', target_words: 800000 },
      });
    });
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });
});

describe('新建项目对话框 — tags 多选 + 自定义新增（#595 拍板 D7=A）', () => {
  it('选择预设标签 + 自定义新增 → POST body 含 tags 数组（多值），不再含 genre', async () => {
    const created = {
      id: 'p9',
      name: '青山入我怀',
      tags: ['玄幻', '仙侠', '热血'],
      language: 'zh-CN',
      target_words: 800000,
      config: {},
      created_at: '2026-08-06T10:00:00Z',
      updated_at: '2026-08-06T10:00:00Z',
    };
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/api/v1/projects') return created;
      return { ok: true };
    });
    const user = userEvent.setup();
    renderHarness();

    await user.click(screen.getByTestId('open-trigger'));
    await user.type(within(screen.getByRole('dialog')).getByLabelText('书名'), '青山入我怀');

    // 打开 tags 多选（combobox，testid tags-select），勾选预设标签（旧 genre 枚举值）
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '玄幻' }));
    await user.click(screen.getByTestId('tags-select'));
    await user.click(await screen.findByRole('option', { name: '仙侠' }));

    // 自定义新增标签（tags-input 输入 + Enter 确认）
    await user.type(screen.getByTestId('tags-input'), '热血{Enter}');

    await user.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/projects', {
        method: 'POST',
        body: { name: '青山入我怀', tags: ['玄幻', '仙侠', '热血'], language: 'zh-CN', target_words: 800000 },
      });
    });
    expect(await screen.findByTestId('writing-probe')).toBeInTheDocument();
  });
});
