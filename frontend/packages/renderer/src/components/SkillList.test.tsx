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
 *
 * #522 P2 Skills 管理 UI 增强（追加契约，2026-08-20，详情滚动 + user_upload 编辑入口）：
 * - 详情弹窗 data-testid="skill-detail-content" 容器加滚动语义（className 含
 *   overflow-y-auto 或 max-h-* 之一，max-height 限制 + 纵向滚动）
 * - user_upload 卡片新增「编辑」按钮 data-testid="skill-edit-<id>"（仅 user_upload
 *   渲染，builtin 不渲染——镜像 detail/copy 只对 builtin、delete 只对 user_upload
 *   的分流）；按钮文案 t('skill.edit')（zh「编辑」/ en「Edit」，新 i18n key）
 * - 编辑弹窗 data-testid="skill-edit-dialog"（独立弹窗，与 skill-upload-dialog 并存）：
 *   textarea data-testid="skill-edit-content" 预填 skill.content 逐字；保存
 *   data-testid="skill-edit-save" → store.updateSkill(name, { content }) →
 *   PATCH /api/v1/skills/{name}（用 skill.name）→ 成功关弹窗 + loadSkills 重拉；
 *   取消 data-testid="skill-edit-cancel" → 关闭不保存（零 PATCH/POST）
 * - store 新增 updateSkill(name: string, patch: { content: string })（本批只组件级契约）
 * - 设计假设与 RED 预期详见文件尾 #522 describe 块注释

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
/*
 * #522 P2 Skills 管理 UI 增强（追加契约，2026-08-20，详情滚动 + user_upload 编辑入口）：
 *
 * 设计假设（GREEN 契约，Codex 照此实现）：
 * 1. 详情弹窗 content 滚动容器：data-testid="skill-detail-content" 元素（pre 或其
 *    包裹容器）className 含 overflow-y-auto 或 max-h-*（max-height + 纵向滚动语义）；
 *    既有 textContent 全文契约不变。
 * 2. user_upload 卡片新增「编辑」按钮 data-testid="skill-edit-<id>"（仅
 *    source === 'user_upload' 渲染；builtin 卡片不渲染 skill-edit- 前缀——镜像
 *    detail/copy 只对 builtin、delete 只对 user_upload 的分流逻辑）；
 *    按钮文案 t('skill.edit')（zh「编辑」/ en「Edit」，新 i18n key，GREEN 补 zh/en）。
 * 3. 点击编辑 → 独立编辑弹窗 data-testid="skill-edit-dialog"（不复用上传弹窗
 *    skill-upload-dialog 的 testid，两弹窗并存）；弹窗内 textarea
 *    data-testid="skill-edit-content"（aria-label 可复用 t('skill.content')），
 *    初始值 = 该 skill.content 逐字（预填）。
 * 4. 保存按钮 data-testid="skill-edit-save"、取消按钮 data-testid="skill-edit-cancel"
 *    （文案可用 t('dlg.cancel')）。
 * 5. 保存 → store.updateSkill(name: string, patch: { content: string })
 *    （GREEN 在 stores/skills.ts 新增；前端 Skill 类型 id 仍为 number，API 路径
 *    用 skill.name）：PATCH /api/v1/skills/{name} body={content} → 成功 →
 *    弹窗关闭 + loadSkills() 重拉列表；失败 → 弹窗不关 + 错误提示（本批不锁失败形态）。
 * 6. 取消 → 弹窗关闭，不发任何 PATCH/POST。
 *
 * RED 预期：滚动断言 assert 类（className 无滚动类）/ skill-edit-<id> 缺失
 * element-missing / skill-edit-dialog 缺失 element-missing / updateSkill 未实现
 * （保存用例在点编辑处即 element-missing，PATCH 断言不达）。
 */
describe('SkillList — P2 详情滚动 + user_upload 编辑（#522）', () => {
  it('详情弹窗 content 容器有滚动语义（overflow-y-auto 或 max-h-*）', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [BUILTIN_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    await user.click(screen.getByTestId('skill-detail-2'));
    const dlg = await screen.findByTestId('skill-detail-dialog');
    expect(dlg).toBeInTheDocument();
    const content = screen.getByTestId('skill-detail-content');
    expect(content.className).toMatch(/overflow-y-auto|max-h-/);
  });

  it('user_upload 卡片渲染编辑按钮 skill-edit-<id>（文案「编辑」）；builtin 卡片不渲染', async () => {
    apiFetchMock.mockResolvedValue({ items: [BUILTIN_SKILL, USER_SKILL], total: 2 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-2');
    const card3 = screen.getByTestId('skill-card-3');
    const editBtn = within(card3).getByTestId('skill-edit-3');
    expect(editBtn).toHaveTextContent('编辑');
    const card2 = screen.getByTestId('skill-card-2');
    expect(within(card2).queryByTestId('skill-edit-2')).not.toBeInTheDocument();
  });

  it('点编辑 → skill-edit-dialog 打开 + textarea 预填 skill.content（独立弹窗）', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [USER_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-3');
    await user.click(screen.getByTestId('skill-edit-3'));
    const dlg = await screen.findByTestId('skill-edit-dialog');
    expect(dlg).toBeInTheDocument();
    // 独立弹窗契约：编辑弹窗不复用上传弹窗 testid
    expect(screen.queryByTestId('skill-upload-dialog')).not.toBeInTheDocument();
    const textarea = within(dlg).getByTestId('skill-edit-content');
    expect(textarea).toHaveValue(USER_SKILL.content);
  });

  it('保存 → PATCH /api/v1/skills/{name} body={content} → 弹窗关闭 + loadSkills 重拉', async () => {
    const user = userEvent.setup();
    const EDITED_CONTENT =
      '---\nname: web-research\ndescription: 网络调研方法论 v2\n---\n# 调研 v2';
    const stateSkills: Skill[] = [{ ...USER_SKILL }];
    apiFetchMock.mockImplementation(
      async (path: string, init?: { method?: string; body?: { content?: string } }) => {
        if (path === '/api/v1/skills/web-research' && init?.method === 'PATCH') {
          const patched: Skill = {
            ...stateSkills[0],
            content: init.body?.content ?? stateSkills[0].content,
            updated_at: '2026-08-20T00:00:00Z',
          };
          stateSkills[0] = patched;
          return patched;
        }
        if (path === '/api/v1/skills') return { items: [...stateSkills], total: stateSkills.length };
        if (path === '/api/v1/agents') return { items: [], total: 0 };
        return { ok: true };
      },
    );
    render(<SkillList />);
    await screen.findByTestId('skill-card-3');
    await user.click(screen.getByTestId('skill-edit-3'));
    const dlg = await screen.findByTestId('skill-edit-dialog');
    const textarea = within(dlg).getByTestId('skill-edit-content');
    await user.clear(textarea);
    await user.type(textarea, EDITED_CONTENT);
    await user.click(within(dlg).getByTestId('skill-edit-save'));
    await waitFor(() => {
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/v1/skills/web-research',
        expect.objectContaining({ method: 'PATCH', body: { content: EDITED_CONTENT } }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId('skill-edit-dialog')).not.toBeInTheDocument();
    });
    // 保存成功后列表刷新（loadSkills 重拉）：GET /skills 至少 2 次（挂载 + 刷新）
    const getCalls = apiFetchMock.mock.calls.filter(
      (c) => c[0] === '/api/v1/skills' && c[1]?.method === undefined,
    );
    expect(getCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('取消 → 弹窗关闭且不发任何 PATCH/POST', async () => {
    const user = userEvent.setup();
    apiFetchMock.mockResolvedValue({ items: [USER_SKILL], total: 1 });
    render(<SkillList />);
    await screen.findByTestId('skill-card-3');
    await user.click(screen.getByTestId('skill-edit-3'));
    const dlg = await screen.findByTestId('skill-edit-dialog');
    await user.click(within(dlg).getByTestId('skill-edit-cancel'));
    await waitFor(() => {
      expect(screen.queryByTestId('skill-edit-dialog')).not.toBeInTheDocument();
    });
    const writeCalls = apiFetchMock.mock.calls.filter(
      (c) => c[1]?.method === 'PATCH' || c[1]?.method === 'POST',
    );
    expect(writeCalls.length).toBe(0);
  });
});
