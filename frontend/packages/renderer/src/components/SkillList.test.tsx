/**
 * ⚠️ 契约文件（F40 #259 SkillList RED 阶段，spec §5.4 管理列表 / §5.6 删除保护）
 *
 * GREEN 新建 src/components/SkillList.tsx，必须匹配：
 *
 * 组件契约（自管理数据：挂载时 loadSkills + loadAgents；删除走 useSkillsStore.deleteSkill）：
 * - props：无（面板级组件，settings.tsx「Skill 管理」分类直接挂载）
 * - 挂载 → GET /api/v1/skills 加载列表（loading 空态「加载中」/ 失败错误文案 skill-list-error）
 * - 列表容器 data-testid="skill-list"；每项 data-testid="skill-card-<id>"：
 *   * name（skill-card-name）+ description（skill-card-desc）
 *   * 来源 badge：builtin → data-testid="skill-source-builtin-<id>" 文案 t('skill.builtin')「内置」；
 *     user_upload → data-testid="skill-source-user-<id>" 文案 t('skill.userUpload')「用户上传」
 *   * 被引用 Agent 反查（spec §5.4 管理列表）：agent_ids.length > 0 →
 *     data-testid="skill-refs-<id>" 文案含「被 N 个 Agent 引用：a、b」（t('skill.refs', {n, names})）；
 *     无引用 → 不渲染该 badge
 * - 「上传 Skill」按钮 data-testid="skill-add-btn" → 打开 SkillUploadDialog
 * - 删除（spec §5.6 删除保护）：
 *   * builtin（source='builtin'）→ **不渲染删除按钮**（内置只读）
 *   * user_upload 无引用 → 删除按钮 data-testid="skill-delete-<id>" → ConfirmDialog
 *     （testidPrefix='skill-confirm'，message = t('skill.deleteConfirm')）
 *   * user_upload 被引用 → 删除按钮 → ConfirmDialog message 含影响面
 *     t('skill.deleteReferenced', {n, names})「该 Skill 被 N 个 Agent 引用：<names>。删除后
 *     引用将自动移除，不可恢复」；确认 → deleteSkill → 列表刷新
 *   * 删除失败（409）→ 错误文案 skill-list-error
 * - 空列表 → 空态文案 t('skill.empty')「还没有 Skill，点击上传」
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：
 * skill.builtin='内置' skill.userUpload='用户上传' skill.refs='被 {n} 个 Agent 引用：{names}'
 * skill.add='上传 Skill' skill.deleteConfirm='删除后不可恢复，确认删除？'
 * skill.deleteReferenced='该 Skill 被 {n} 个 Agent 引用：{names}。删除后引用将自动移除，不可恢复'
 * skill.empty='还没有 Skill，点击上传' skill.listTitle='Skill 管理'
 *
 * #485 内置 Skill 详情 + 复制（追加契约，2026-08-19）：
 * - 内置 skill 卡片（source='builtin'）新增「详情」data-testid=skill-detail-{id}、「复制」
 *   data-testid=skill-copy-{id}；user_upload 卡片不渲染 skill-detail- / skill-copy- 前缀
 * - 「详情」→ 弹层 data-testid=skill-detail-dialog：content 全文 data-testid=skill-detail-content
 *   （textContent 含该 skill.content 逐字）；关闭按钮 data-testid=skill-detail-close
 * - 「复制」→ store copySkill(id)：POST /api/v1/skills/{id}/duplicate → 成功 toast
 *   t('skill.copied')「已复制」（新 i18n key，GREEN 补 zh/en）+ 副本进列表（source=user_upload →
 *   skill-source-user-{id} 可删）；失败 → t('toast.saveFailed')「保存失败」
 *   （刷新实现不锁：copySkill 内部追加或 loadSkills 重拉均可；状态化 mock 保证两条路径都能看到副本卡）
 *
 * RED 预期：./SkillList 模块不存在 → module-not-found（类 1 契约缺口，suite 级失败）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SkillList } from './SkillList';
import { useSkillsStore, type Skill } from '../stores/skills';
import { useAgentsStore } from '../stores/agents';
import { useToastStore } from '../stores/toast';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const USER_SKILL: Skill = {
  id: 3,
  name: 'web-research',
  description: '网络调研方法论',
  content: '---\nname: web-research\ndescription: 网络调研方法论\n---\n# 调研',
  source: 'user_upload',
  created_at: '2026-08-16T00:00:00Z',
  updated_at: '2026-08-16T00:00:00Z',
  agent_ids: [],
};

const REFERENCED_SKILL: Skill = {
  ...USER_SKILL,
  id: 4,
  name: 'outline-method',
  description: '大纲方法论',
  agent_ids: [
    { id: 5, name: '我的润色师' },
    { id: 2, name: '架构师' },
  ],
};

const BUILTIN_SKILL: Skill = {
  id: 2,
  name: '架构方法论',
  description: '章节结构/大纲规划方法论',
  content: '---\nname: 架构方法论\ndescription: 章节结构/大纲规划方法论\n---\n# 架构',
  source: 'builtin',
  created_at: '2026-08-16T00:00:00Z',
  updated_at: '2026-08-16T00:00:00Z',
  agent_ids: [],
};

beforeEach(() => {
  apiFetchMock.mockReset();
  useSkillsStore.setState({ skills: [], loading: false, error: null });
  useAgentsStore.setState({ agents: [], loading: false, error: null });
  useToastStore.setState({ toasts: [] });
});

describe('SkillList — 列表渲染', () => {
  it('挂载时 GET /skills + 渲染 name/description/来源 badge/反查', async () => {
    apiFetchMock.mockResolvedValue({
      items: [BUILTIN_SKILL, USER_SKILL, REFERENCED_SKILL],
      total: 3,
    });
    render(<SkillList />);
    await screen.findByTestId('skill-card-3');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills');

    // 来源 badge
    expect(screen.getByTestId('skill-source-builtin-2')).toHaveTextContent('内置');
    expect(screen.getByTestId('skill-source-user-3')).toHaveTextContent('用户上传');

    // 反查 badge（仅被引用项渲染）
    const refs = screen.getByTestId('skill-refs-4');
    expect(refs).toHaveTextContent('我的润色师');
    expect(refs).toHaveTextContent('架构师');
    expect(screen.queryByTestId('skill-refs-3')).not.toBeInTheDocument();
    expect(screen.queryByTestId('skill-refs-2')).not.toBeInTheDocument();
  });

  it('加载失败 → 错误文案', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核离线'));
    render(<SkillList />);
    const err = await screen.findByTestId('skill-list-error');
    expect(err.textContent?.length).toBeGreaterThan(0);
  });

  it('空列表 → 空态文案', async () => {
    apiFetchMock.mockResolvedValue({ items: [], total: 0 });
    render(<SkillList />);
    const empty = await screen.findByTestId('skill-empty');
    expect(empty.textContent?.length).toBeGreaterThan(0);
  });
});

describe('SkillList — 删除保护（spec §5.6）', () => {
  it('内置 skill 不渲染删除按钮（只读）', async () => {
    apiFetchMock.mockResolvedValue({ items: [BUILTIN_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    expect(screen.queryByTestId('skill-delete-2')).not.toBeInTheDocument();
  });

  it('user_upload 无引用 → 删除按钮 → ConfirmDialog 通用文案 → 确认删除', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [USER_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-3');
    await user.click(screen.getByTestId('skill-delete-3'));
    const dlg = await screen.findByTestId('skill-confirm-dialog');
    expect(dlg).toBeInTheDocument();

    // 确认 → DELETE
    apiFetchMock.mockResolvedValue(undefined);
    await user.click(within(dlg).getByTestId('skill-confirm-ok'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills/3', { method: 'DELETE' });
    });
  });

  it('user_upload 被引用 → ConfirmDialog 列影响面（agent 名）', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [REFERENCED_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-4');
    await user.click(screen.getByTestId('skill-delete-4'));
    const dlg = await screen.findByTestId('skill-confirm-dialog');
    const message = within(dlg).getByTestId('skill-confirm-message');
    expect(message).toHaveTextContent('我的润色师');
    expect(message).toHaveTextContent('架构师');
  });

  it('删除失败（409 内置）→ 错误文案 + 列表不变', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValueOnce({ items: [USER_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-3');
    await user.click(screen.getByTestId('skill-delete-3'));
    const dlg = await screen.findByTestId('skill-confirm-dialog');
    apiFetchMock.mockRejectedValueOnce(new Error('内置 Skill 只读'));
    await user.click(within(dlg).getByTestId('skill-confirm-ok'));
    const err = await screen.findByTestId('skill-list-error');
    expect(err.textContent).toContain('内置');
    expect(screen.getByTestId('skill-card-3')).toBeInTheDocument();
  });
});

describe('SkillList — 上传入口', () => {
  it('「上传 Skill」按钮 → SkillUploadDialog 打开', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [], total: 0 });
    render(<SkillList />);
    await screen.findByTestId('skill-add-btn');
    await user.click(screen.getByTestId('skill-add-btn'));
    expect(await screen.findByTestId('skill-upload-dialog')).toBeInTheDocument();
  });
});

describe('SkillList — 内置详情 + 复制（#485）', () => {
  it('内置 skill 卡片有详情+复制按钮；user_upload 卡片无（skill-detail-/skill-copy- 前缀仅 builtin）', async () => {
    apiFetchMock.mockResolvedValue({ items: [BUILTIN_SKILL, USER_SKILL], total: 2 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    const card2 = screen.getByTestId('skill-card-2');
    expect(within(card2).getByTestId('skill-detail-2')).toBeInTheDocument();
    expect(within(card2).getByTestId('skill-copy-2')).toBeInTheDocument();
    const card3 = screen.getByTestId('skill-card-3');
    expect(within(card3).queryByTestId('skill-detail-3')).not.toBeInTheDocument();
    expect(within(card3).queryByTestId('skill-copy-3')).not.toBeInTheDocument();
  });

  it('点详情 → 弹层：content 全文 + 关闭按钮可关闭', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [BUILTIN_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    await user.click(screen.getByTestId('skill-detail-2'));
    const dlg = await screen.findByTestId('skill-detail-dialog');
    expect(dlg).toBeInTheDocument();
    expect(screen.getByTestId('skill-detail-content').textContent).toContain(BUILTIN_SKILL.content);
    await user.click(screen.getByTestId('skill-detail-close'));
    await waitFor(() => {
      expect(screen.queryByTestId('skill-detail-dialog')).not.toBeInTheDocument();
    });
  });

  it('点复制 → POST /api/v1/skills/2/duplicate → toast「已复制」+ 副本卡进列表（skill-source-user-10）', async () => {
    const user = userEvent.setup();
    // 状态化 mock：POST duplicate 后副本进入共享数组，GET /skills 读同一数组——
    // 「copySkill 内部追加」与「loadSkills 重拉」两种刷新实现都能看到副本卡
    const stateSkills: Skill[] = [BUILTIN_SKILL];
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/skills/2/duplicate' && init?.method === 'POST') {
        const copied: Skill = { ...BUILTIN_SKILL, id: 10, name: '架构方法论 副本', source: 'user_upload', agent_ids: [] };
        stateSkills.push(copied);
        return copied;
      }
      if (path === '/api/v1/skills') return { items: [...stateSkills], total: stateSkills.length };
      if (path === '/api/v1/agents') return { items: [], total: 0 };
      return { ok: true };
    });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    await user.click(screen.getByTestId('skill-copy-2'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/skills/2/duplicate',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message.includes('已复制'))).toBe(true);
    });
    expect(await screen.findByTestId('skill-card-10')).toBeInTheDocument();
    expect(screen.getByTestId('skill-source-user-10')).toHaveTextContent('用户上传');
  });

  it('复制失败 → 错误 toast（toast.saveFailed）', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/skills/2/duplicate' && init?.method === 'POST') {
        throw new Error('duplicate failed');
      }
      if (path === '/api/v1/skills') return { items: [BUILTIN_SKILL], total: 1 };
      if (path === '/api/v1/agents') return { items: [], total: 0 };
      return { ok: true };
    });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    await user.click(screen.getByTestId('skill-copy-2'));
    await waitFor(() => {
      expect(useToastStore.getState().toasts.some((t) => t.message.includes('保存失败'))).toBe(true);
    });
  });
});
