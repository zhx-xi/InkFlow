/**
 * ⚠️ 契约文件（F40 #259 skill store RED 阶段，spec §3.1 / §3.2 / §5.4）
 *
 * GREEN 新建 src/stores/skills.ts，必须匹配：
 *
 * 导出：
 * - useSkillsStore（zustand store）
 * - 类型（结构契约，字段名不可改）：
 *   SkillRef = { id: number; name: string }                       // agent_ids 反查项
 *   Skill = { id: number; name: string; description: string; content: string;
 *     source: 'builtin' | 'user_upload'; created_at: string; updated_at: string;
 *     agent_ids: SkillRef[] }                                     // 反查（列表端点即含）
 *   SkillListResponse = { items: Skill[]; total: number }
 *
 * 状态：
 * - skills: Skill[]（初始 []）
 * - loading: boolean（初始 false）
 * - error: string | null（初始 null）
 *
 * actions（签名即契约）：
 * - loadSkills(): Promise<void>
 *     GET /api/v1/skills；响应 = { items, total }（items 含 agent_ids 反查）；
 *     成功 → skills 填充 + loading false；失败 → error + 保留原列表
 * - uploadSkill(content: string): Promise<Skill>
 *     POST /api/v1/skills（body = { content }，201）→ 新 Skill 追加到列表尾部并返回；
 *     失败（422 frontmatter 非法/同名、409 等）→ error + rethrow（保存流程需感知失败，
 *     同 templates.createTemplate 语义）
 * - deleteSkill(id: number): Promise<void>
 *     DELETE /api/v1/skills/{id}；成功 → 从列表移除；失败（409 内置只读）→ error +
 *     列表不变（不 rethrow，同 templates.deleteTemplate 语义）
 *
 * RED 预期：./skills 模块不存在 → module-not-found（类 1 契约缺口，suite 级失败）。
 *
 * 2026-08-16 父侧修正（GREEN 后）：ApiError 构造签名与仓库不符——仓库为
 * `constructor(status: number, detail: string)`（2 参），本文件原先误用
 * `new ApiError(message, status, code)` 3 参形态。修正为 `(status, detail)`。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useSkillsStore, type Skill } from './skills';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const SKILLS: Skill[] = [
  {
    id: 1,
    name: 'web-research',
    description: '网络调研方法论',
    content: '---\nname: web-research\ndescription: 网络调研方法论\n---\n# 调研',
    source: 'user_upload',
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T00:00:00Z',
    agent_ids: [{ id: 2, name: '写手' }],
  },
  {
    id: 2,
    name: '架构方法论',
    description: '章节结构/大纲规划方法论',
    content: '---\nname: 架构方法论\ndescription: 章节结构/大纲规划方法论\n---\n# 架构',
    source: 'builtin',
    created_at: '2026-08-16T00:00:00Z',
    updated_at: '2026-08-16T00:00:00Z',
    agent_ids: [],
  },
];

beforeEach(() => {
  apiFetchMock.mockReset();
  useSkillsStore.setState({ skills: [], loading: false, error: null });
});

describe('useSkillsStore.loadSkills', () => {
  it('成功：填充 skills（含 agent_ids 反查）+ loading false + error null', async () => {
    apiFetchMock.mockResolvedValue({ items: SKILLS, total: 2 });
    await useSkillsStore.getState().loadSkills();
    const s = useSkillsStore.getState();
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills');
    expect(s.skills).toEqual(SKILLS);
    expect(s.skills[0].agent_ids).toEqual([{ id: 2, name: '写手' }]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('失败：error 设置 + 原列表保留', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(0, '内核离线'));
    await useSkillsStore.getState().loadSkills();
    const s = useSkillsStore.getState();
    expect(s.error).toContain('内核离线');
    expect(s.skills).toEqual([]);
  });
});

describe('useSkillsStore.uploadSkill', () => {
  const NEW: Skill = {
    id: 9,
    name: 'outline-method',
    description: '大纲方法论',
    content: '---\nname: outline-method\ndescription: 大纲方法论\n---\n# 大纲',
    source: 'user_upload',
    created_at: '2026-08-16T01:00:00Z',
    updated_at: '2026-08-16T01:00:00Z',
    agent_ids: [],
  };

  it('成功：POST body {content} → 追加列表尾部并返回实体', async () => {
    apiFetchMock.mockResolvedValue(NEW);
    const created = await useSkillsStore.getState().uploadSkill(NEW.content);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills', {
      method: 'POST',
      body: { content: NEW.content },
    });
    expect(created).toEqual(NEW);
    expect(useSkillsStore.getState().skills).toContainEqual(NEW);
  });

  it('失败（422）：error 设置 + rethrow + 列表不变', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(422, 'frontmatter 缺少 name'));
    await expect(useSkillsStore.getState().uploadSkill('bad')).rejects.toThrow();
    const s = useSkillsStore.getState();
    expect(s.error).toContain('frontmatter');
    expect(s.skills).toEqual([]);
  });
});

describe('useSkillsStore.deleteSkill', () => {
  it('成功：DELETE → 从列表移除', async () => {
    useSkillsStore.setState({ skills: SKILLS });
    apiFetchMock.mockResolvedValue(undefined);
    await useSkillsStore.getState().deleteSkill(1);
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/skills/1', { method: 'DELETE' });
    expect(useSkillsStore.getState().skills.map((s) => s.id)).toEqual([2]);
  });

  it('失败（409 内置只读）：error 设置 + 列表不变 + 不 rethrow', async () => {
    useSkillsStore.setState({ skills: SKILLS });
    apiFetchMock.mockRejectedValue(new ApiError(409, '内置 Skill 只读'));
    await useSkillsStore.getState().deleteSkill(2);
    const s = useSkillsStore.getState();
    expect(s.error).toContain('内置');
    expect(s.skills.map((x) => x.id)).toEqual([1, 2]);
  });
});
