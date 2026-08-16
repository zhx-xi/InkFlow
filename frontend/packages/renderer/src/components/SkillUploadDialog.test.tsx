/**
 * ⚠️ 契约文件（F40 #259 SkillUploadDialog RED 阶段，spec §5.4 上传+绑定 / D1 拍板）
 *
 * GREEN 新建 src/components/SkillUploadDialog.tsx，必须匹配：
 *
 * 组件契约（受控弹窗，真实 API 调用——上传走 useSkillsStore.uploadSkill，绑定走
 * useAgentsStore.bindSkill）：
 * - props：{ open: boolean; onOpenChange(open: boolean): void; onUploaded?(skill: Skill): void }
 * - open=true → role=dialog + data-testid="skill-upload-dialog"；标题「上传 Skill」；open=false → 不渲染
 *
 * 上传区（frontmatter 解析预览，契约锚点 spec §5.4 步骤「上传」）：
 * - 文本域 textarea aria-label「SKILL.md 内容」+ data-testid="skill-upload-content"（可粘贴全文）
 * - 内容非空 → 实时解析预览 data-testid="skill-upload-preview"：
 *   * 合法：显示 name（skill-upload-preview-name）/ description（skill-upload-preview-desc）/
 *     tags（skill-upload-preview-tags，无 tags 隐藏）
 *   * 非法：显示错误文案（skill-upload-preview-error，t('skill.fmError')「frontmatter 不合法」），
 *     上传按钮禁用
 * - 空内容：无预览，上传按钮禁用
 *
 * 绑定区（D1 拍板：默认不勾选 + 可搜索 + 应用到全部；内置禁用）：
 * - 标题「绑定到 Agent（可选）」+ 提示 t('skill.bindHint')「默认不绑定，避免 Agent 行为意外改变」
 * - 搜索框 input data-testid="skill-bind-search" aria-label「搜索 Agent」（按 name 过滤候选）
 * - Agent 候选 checkbox 列表 data-testid="skill-bind-agent-<id>"：
 *   * 每项 label = agent.name + (builtin ? 「内置只读」badge : '')
 *   * **默认全部不勾选**（D1 铁律：AI 自动化默认关闭）
 *   * builtin=true 的 Agent checkbox disabled（后端 PATCH 内置 → 409，spec §5.6）
 * - 「应用到全部」按钮 data-testid="skill-bind-all"：点击 → 勾选全部**非内置** Agent
 *   （内置仍禁用）；再点 → 取消勾选全部非内置（toggle 语义）
 * - 候选加载失败 → 绑定区显示错误文案（skill-bind-error）+ 不渲染 checkbox
 *
 * 按钮：
 * - 上传 data-testid="skill-upload-submit"（文案「上传」ag.save 或 t('skill.upload')）：
 *   * 流程 = await uploadSkill(content) → 若勾选非空 Agent → 逐个 await bindSkill(agentId, newSkill.id)
 *     → onOpenChange(false) + onUploaded(newSkill)
 *   * 任一步失败 → 不关闭 + 错误文案显示（skill-upload-error）+ 已上传成功的 skill 不回滚
 *     （上传成功但绑定失败：错误提示「上传成功，绑定失败：<err>」）
 * - 取消 data-testid="skill-upload-cancel"（文案「取消」dlg.cancel）→ onOpenChange(false)
 * - 提交中按钮 disabled（防重复提交）
 *
 * 新增 i18n key（GREEN 补 zh.ts / en.ts）：
 * skill.upload='上传 Skill' skill.content='SKILL.md 内容' skill.fmError='frontmatter 不合法'
 * skill.bindTitle='绑定到 Agent（可选）' skill.bindHint='默认不绑定，避免 Agent 行为意外改变'
 * skill.bindAll='应用到全部' skill.builtinBadge='内置只读' skill.searchAgent='搜索 Agent'
 * skill.uploadBtn='上传' skill.bindFail='上传成功，绑定失败' skill.bindEmpty='请先粘贴 SKILL.md 内容'
 *
 * RED 预期：./SkillUploadDialog 模块不存在 → module-not-found（类 1 契约缺口，suite 级失败）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SkillUploadDialog } from './SkillUploadDialog';
import { useSkillsStore, type Skill } from '../stores/skills';
import { useAgentsStore, type AgentEntity } from '../stores/agents';
import { apiFetch } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const AGENTS: AgentEntity[] = [
  {
    id: 1,
    name: '写手',
    description: '正文生成',
    icon: '✍️',
    system_prompt: '你是写手',
    tool_ids: ['save_draft'],
    skill_ids: ['2'],
    model_override: null,
    temperature_override: null,
    builtin: true,
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T00:00:00Z',
  },
  {
    id: 5,
    name: '我的润色师',
    description: '自定义润色',
    icon: '✨',
    system_prompt: '你是润色师',
    tool_ids: ['count_words'],
    skill_ids: [],
    model_override: null,
    temperature_override: null,
    builtin: false,
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T00:00:00Z',
  },
];

const NEW_SKILL: Skill = {
  id: 9,
  name: 'outline-method',
  description: '大纲方法论',
  content: '---\nname: outline-method\ndescription: 大纲方法论\n---\n# 大纲',
  source: 'user_upload',
  created_at: '2026-08-16T01:00:00Z',
  updated_at: '2026-08-16T01:00:00Z',
  agent_ids: [],
};

const VALID_CONTENT = `---
name: outline-method
description: 大纲方法论
---
# 大纲
- 先规划`;

const INVALID_CONTENT = `---
description: 缺 name
---
# 非法`;

function renderDialog(open = true) {
  const onOpenChange = vi.fn();
  const onUploaded = vi.fn();
  const utils = render(
    <SkillUploadDialog open={open} onOpenChange={onOpenChange} onUploaded={onUploaded} />
  );
  return { onOpenChange, onUploaded, ...utils };
}

beforeEach(() => {
  apiFetchMock.mockReset();
  useSkillsStore.setState({ skills: [], loading: false, error: null });
  useAgentsStore.setState({ agents: [], loading: false, error: null });
  // 候选 Agent 加载：默认 mock GET /agents
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path === '/api/v1/agents') return { items: AGENTS, total: 2 };
    throw new Error(`unexpected fetch: ${path}`);
  });
});

describe('SkillUploadDialog — 渲染', () => {
  it('open=false → 不渲染；open=true → dialog + 标题', () => {
    const { unmount } = renderDialog(false);
    expect(screen.queryByTestId('skill-upload-dialog')).not.toBeInTheDocument();
    unmount();
    renderDialog(true);
    expect(screen.getByTestId('skill-upload-dialog')).toBeInTheDocument();
    expect(screen.getByText('上传 Skill')).toBeInTheDocument();
  });

  it('挂载时加载 Agent 候选（GET /agents）', async () => {
    renderDialog(true);
    await screen.findByTestId('skill-bind-agent-5');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents');
  });
});

describe('SkillUploadDialog — frontmatter 预览', () => {
  it('空内容：无预览 + 上传禁用', async () => {
    renderDialog(true);
    expect(screen.queryByTestId('skill-upload-preview')).not.toBeInTheDocument();
    expect(screen.getByTestId('skill-upload-submit')).toBeDisabled();
  });

  it('合法内容 → 预览 name/description/tags', async () => {
    const user = userEvent.setup();
    renderDialog(true);
    await user.type(screen.getByTestId('skill-upload-content'), VALID_CONTENT);
    const preview = await screen.findByTestId('skill-upload-preview');
    expect(within(preview).getByTestId('skill-upload-preview-name')).toHaveTextContent('outline-method');
    expect(within(preview).getByTestId('skill-upload-preview-desc')).toHaveTextContent('大纲方法论');
    expect(within(preview).queryByTestId('skill-upload-preview-tags')).not.toBeInTheDocument();
  });

  it('非法内容 → 错误文案 + 上传禁用', async () => {
    const user = userEvent.setup();
    renderDialog(true);
    await user.type(screen.getByTestId('skill-upload-content'), INVALID_CONTENT);
    const err = await screen.findByTestId('skill-upload-preview-error');
    expect(err.textContent?.length).toBeGreaterThan(0);
    expect(screen.getByTestId('skill-upload-submit')).toBeDisabled();
  });
});

describe('SkillUploadDialog — 绑定区（D1）', () => {
  it('候选列表渲染：Agent 名 + 内置 badge；内置 checkbox 禁用', async () => {
    renderDialog(true);
    const agent5 = await screen.findByTestId('skill-bind-agent-5');
    expect(agent5).toHaveTextContent('我的润色师');
    const agent1 = screen.getByTestId('skill-bind-agent-1');
    expect(agent1).toHaveTextContent('写手');
    expect(agent1).toHaveTextContent('内置只读');
    expect(within(agent1).getByRole('checkbox')).toBeDisabled();
  });

  it('🔴 默认全部不勾选（D1 铁律：AI 自动化默认关闭）', async () => {
    renderDialog(true);
    const agent5 = await screen.findByTestId('skill-bind-agent-5');
    expect(within(agent5).getByRole('checkbox')).not.toBeChecked();
    expect(within(screen.getByTestId('skill-bind-agent-1')).getByRole('checkbox')).not.toBeChecked();
  });

  it('应用到全部 → 勾选全部非内置（内置仍禁用）', async () => {
    const user = userEvent.setup();
    renderDialog(true);
    await screen.findByTestId('skill-bind-agent-5');
    await user.click(screen.getByTestId('skill-bind-all'));
    expect(within(screen.getByTestId('skill-bind-agent-5')).getByRole('checkbox')).toBeChecked();
    expect(within(screen.getByTestId('skill-bind-agent-1')).getByRole('checkbox')).not.toBeChecked();
    // toggle：再点 → 取消
    await user.click(screen.getByTestId('skill-bind-all'));
    expect(within(screen.getByTestId('skill-bind-agent-5')).getByRole('checkbox')).not.toBeChecked();
  });

  it('搜索框按 name 过滤候选', async () => {
    const user = userEvent.setup();
    renderDialog(true);
    await screen.findByTestId('skill-bind-agent-5');
    await user.type(screen.getByTestId('skill-bind-search'), '润色');
    expect(screen.getByTestId('skill-bind-agent-5')).toBeInTheDocument();
    expect(screen.queryByTestId('skill-bind-agent-1')).not.toBeInTheDocument();
  });

  it('候选加载失败 → 绑定区错误文案 + 无 checkbox', async () => {
    apiFetchMock.mockRejectedValue(new Error('内核离线'));
    renderDialog(true);
    const err = await screen.findByTestId('skill-bind-error');
    expect(err.textContent?.length).toBeGreaterThan(0);
    expect(screen.queryByTestId('skill-bind-agent-5')).not.toBeInTheDocument();
  });
});

describe('SkillUploadDialog — 提交流程', () => {
  it('上传成功未勾选 Agent → 仅 POST /skills，不 PATCH agents，关闭 + onUploaded', async () => {
    const user = userEvent.setup();
    const { onOpenChange, onUploaded } = renderDialog(true);
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agents') return { items: AGENTS, total: 2 };
      if (path === '/api/v1/skills' && init?.method === 'POST') return NEW_SKILL;
      throw new Error(`unexpected fetch: ${path}`);
    });
    await user.type(screen.getByTestId('skill-upload-content'), VALID_CONTENT);
    await user.click(screen.getByTestId('skill-upload-submit'));
    await screen.findByTestId('skill-upload-dialog');
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills', {
      method: 'POST',
      body: { content: VALID_CONTENT },
    });
    // 未勾选 → 无 agents PATCH
    const patchCalls = apiFetchMock.mock.calls.filter(
      ([p, i]) => p.startsWith('/api/v1/agents/') && i?.method === 'PATCH'
    );
    expect(patchCalls).toHaveLength(0);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onUploaded).toHaveBeenCalledWith(NEW_SKILL);
  });

  it('上传成功 + 勾选自定义 Agent → POST 后逐个 PATCH agents 追加 skill_ids', async () => {
    const user = userEvent.setup();
    const { onOpenChange, onUploaded } = renderDialog(true);
    const updatedAgent: AgentEntity = { ...AGENTS[1], skill_ids: ['9'] };
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agents') return { items: AGENTS, total: 2 };
      if (path === '/api/v1/skills' && init?.method === 'POST') return NEW_SKILL;
      if (path === '/api/v1/agents/5' && init?.method === 'PATCH') return updatedAgent;
      throw new Error(`unexpected fetch: ${path}`);
    });
    await user.type(screen.getByTestId('skill-upload-content'), VALID_CONTENT);
    await user.click(screen.getByTestId('skill-bind-agent-5'));
    await user.click(screen.getByTestId('skill-upload-submit'));
    // 等待 PATCH 完成（async 链）
    await new Promise((r) => setTimeout(r, 50));
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills', {
      method: 'POST',
      body: { content: VALID_CONTENT },
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agents/5', {
      method: 'PATCH',
      body: { skill_ids: ['9'] },
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onUploaded).toHaveBeenCalledWith(NEW_SKILL);
  });

  it('绑定失败 → 不关闭 + 错误提示（skill-upload-error）', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog(true);
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agents') return { items: AGENTS, total: 2 };
      if (path === '/api/v1/skills' && init?.method === 'POST') return NEW_SKILL;
      if (path === '/api/v1/agents/5' && init?.method === 'PATCH') {
        throw new Error('内置 Agent 只读');
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    await user.type(screen.getByTestId('skill-upload-content'), VALID_CONTENT);
    await user.click(screen.getByTestId('skill-bind-agent-5'));
    await user.click(screen.getByTestId('skill-upload-submit'));
    const err = await screen.findByTestId('skill-upload-error');
    expect(err.textContent?.length).toBeGreaterThan(0);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it('上传失败（422 frontmatter 非法）→ 不关闭 + 错误提示', async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog(true);
    apiFetchMock.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (path === '/api/v1/agents') return { items: AGENTS, total: 2 };
      if (path === '/api/v1/skills' && init?.method === 'POST') {
        throw new Error('frontmatter 不合法');
      }
      throw new Error(`unexpected fetch: ${path}`);
    });
    // 预览合法（后端才 422——同名场景）
    await user.type(screen.getByTestId('skill-upload-content'), VALID_CONTENT);
    await user.click(screen.getByTestId('skill-upload-submit'));
    const err = await screen.findByTestId('skill-upload-error');
    expect(err.textContent).toContain('frontmatter');
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
