/**
 * ⚠️ 契约文件（Issue #107 Agent 模板 store RED 阶段，spec §9.2 / §9.3 / §9.5）
 *
 * GREEN 新建 src/stores/templates.ts，必须匹配：
 *
 * 导出：
 * - useTemplatesStore（zustand store）
 * - 类型（结构契约，字段名不可改）：
 *   AgentTemplateRole = { model: string | null; temperature: number | null; enabled: boolean }
 *   AgentTemplate = { id: number; name: string; description: string; main_model: string;
 *     default_temperature: number;
 *     roles: { architect: AgentTemplateRole; writer: AgentTemplateRole;
 *       auditor: AgentTemplateRole; reviser: AgentTemplateRole };
 *     default_words: number; is_default: boolean;
 *     used_by?: Array<{ id: string; name: string }>;
 *     created_at: string; updated_at: string }
 *   AgentTemplateInput = { name, description, main_model, default_temperature,
 *     roles: { architect/writer/auditor/reviser: AgentTemplateRole }, default_words }
 *     （创建/更新请求体；不含 id / is_default / used_by / 时间戳）
 *
 * 状态：
 * - templates: AgentTemplate[]（初始 []）
 * - loading: boolean（初始 false）
 * - error: string | null（初始 null）
 * - defaultTemplateId: number | null（初始 null；默认模板 id，loadDefault / setDefault 维护）
 *
 * actions（签名即契约）：
 * - loadTemplates(): Promise<void>
 *     GET /api/v1/agent-templates；响应 = FastAPI 列表包装 { items, total, offset, limit }
 *     （§4.4 列表端点惯例，非裸数组）；列表项含 used_by（前端契约：列表即完整实体，
 *     面板徽标 / 风险确认直接可读——若后端列表端点不含 used_by，GREEN 需在面板内
 *     按模板补拉 GET /api/v1/agent-templates/{id}，测试 mock 需相应调整）；
 *     成功 → templates 填充 + loading false；失败 → error + 保留原列表
 * - createTemplate(input: AgentTemplateInput): Promise<AgentTemplate>
 *     POST /api/v1/agent-templates（body = input，201）→ 创建结果追加到列表尾部并返回；
 *     失败 → error + rethrow（保存流程需感知失败，同 models.addProvider #125 语义）
 * - updateTemplate(id: number, patch: Partial<AgentTemplateInput>): Promise<AgentTemplate>
 *     PATCH /api/v1/agent-templates/{id}（body = patch）→ 列表项以响应为准替换；
 *     失败 → error + rethrow + 列表不变
 * - deleteTemplate(id: number): Promise<void>
 *     DELETE /api/v1/agent-templates/{id}；成功 → 从列表移除；
 *     失败 → error + 列表不变（不 rethrow，同 models.deleteProvider）
 * - duplicateTemplate(id: number): Promise<AgentTemplate>
 *     POST /api/v1/agent-templates/{id}/duplicate → 复制结果追加到列表尾部并返回；
 *     失败 → error + rethrow + 列表不变
 * - setDefault(id: number): Promise<void>
 *     PATCH /api/v1/agent-templates/default（body { id }）→ 成功：defaultTemplateId = id +
 *     列表内 is_default 标志翻转（目标 true，其余 false）；失败 → error（不 rethrow）
 * - loadDefault(): Promise<void>
 *     GET /api/v1/agent-templates/default → 响应为模板实体（含 id）→ defaultTemplateId = data.id；
 *     失败 → error（不 rethrow）
 *
 * RED 预期：./templates 模块不存在 → module-not-found（类 1 契约缺口，suite 级失败，
 * 0 test 计数）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { act } from '@testing-library/react';
import { useTemplatesStore, type AgentTemplate, type AgentTemplateInput } from './templates';
import { apiFetch, ApiError } from '../api/client';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

const ROLE = (model: string | null, temperature: number | null, enabled: boolean) => ({
  model,
  temperature,
  enabled,
});

const TEMPLATES: AgentTemplate[] = [
  {
    id: 1,
    name: '经典玄幻',
    description: '标准玄幻创作模板',
    main_model: 'gpt-4o',
    default_temperature: 0.7,
    roles: {
      architect: ROLE('deepseek-chat', 0.4, true),
      writer: ROLE('gpt-4o', 0.8, true),
      auditor: ROLE('gpt-4o', 0.5, true),
      reviser: ROLE('deepseek-chat', 0.6, true),
    },
    default_words: 800000,
    is_default: true,
    used_by: [
      { id: 'p1', name: '青云志' },
      { id: 'p2', name: '归墟记' },
    ],
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
      architect: ROLE(null, null, true),
      writer: ROLE('deepseek-chat', 0.9, true),
      auditor: ROLE(null, null, true),
      reviser: ROLE(null, null, true),
    },
    default_words: 600000,
    is_default: false,
    used_by: [],
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-05T10:00:00Z',
  },
];

const CREATE_INPUT: AgentTemplateInput = {
  name: '我的模板',
  description: '测试用模板',
  main_model: 'gpt-4o',
  default_temperature: 0.8,
  roles: {
    architect: ROLE('deepseek-chat', 0.5, true),
    writer: ROLE(null, null, true),
    auditor: ROLE(null, null, true),
    reviser: ROLE(null, null, true),
  },
  default_words: 500000,
};

beforeEach(() => {
  apiFetchMock.mockReset();
  localStorage.clear();
  useTemplatesStore.setState({ templates: [], loading: false, error: null, defaultTemplateId: null });
});

describe('templates store — 契约面（GREEN 必须提供）', () => {
  it('暴露 actions: loadTemplates / createTemplate / updateTemplate / deleteTemplate / duplicateTemplate / setDefault / loadDefault', () => {
    const s = useTemplatesStore.getState();
    expect(typeof s.loadTemplates).toBe('function');
    expect(typeof s.createTemplate).toBe('function');
    expect(typeof s.updateTemplate).toBe('function');
    expect(typeof s.deleteTemplate).toBe('function');
    expect(typeof s.duplicateTemplate).toBe('function');
    expect(typeof s.setDefault).toBe('function');
    expect(typeof s.loadDefault).toBe('function');
  });
});

describe('templates store — 初始态', () => {
  it('templates 空 / loading false / error null / defaultTemplateId null', () => {
    const s = useTemplatesStore.getState();
    expect(s.templates).toEqual([]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
    expect(s.defaultTemplateId).toBeNull();
  });
});

describe('templates store — 模板列表加载', () => {
  it('loadTemplates 成功：GET /api/v1/agent-templates → {items} → templates 填充 + loading false', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent-templates');
    const s = useTemplatesStore.getState();
    expect(s.templates).toHaveLength(2);
    expect(s.templates[0].name).toBe('经典玄幻');
    expect(s.templates[0].used_by).toHaveLength(2);
    expect(s.templates[0].is_default).toBe(true);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('loadTemplates 失败：error 设置 + 原列表保留', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    apiFetchMock.mockRejectedValue(new ApiError(500, '内核异常'));
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    const s = useTemplatesStore.getState();
    expect(s.error).toContain('内核异常');
    expect(s.templates).toHaveLength(2); // 失败不覆盖已加载列表
  });

  it('loadTemplates 挂起期间 loading=true，完成后复位 false', async () => {
    let resolveFetch!: (v: unknown) => void;
    apiFetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    let p!: Promise<void>;
    act(() => {
      p = useTemplatesStore.getState().loadTemplates();
    });
    expect(useTemplatesStore.getState().loading).toBe(true);

    resolveFetch({ items: [], total: 0, offset: 0, limit: 50 });
    await act(async () => {
      await p;
    });
    expect(useTemplatesStore.getState().loading).toBe(false);
  });
});

describe('templates store — 创建 / 更新', () => {
  it('createTemplate 成功：POST /api/v1/agent-templates（body = input）→ 新模板追加列表尾部并返回', async () => {
    const created: AgentTemplate = {
      id: 3,
      name: '我的模板',
      description: '测试用模板',
      main_model: 'gpt-4o',
      default_temperature: 0.8,
      roles: { ...CREATE_INPUT.roles },
      default_words: 500000,
      is_default: false,
      used_by: [],
      created_at: '2026-08-06T10:00:00Z',
      updated_at: '2026-08-06T10:00:00Z',
    };
    apiFetchMock.mockResolvedValue(created);
    let returned!: AgentTemplate;
    await act(async () => {
      returned = await useTemplatesStore.getState().createTemplate(CREATE_INPUT);
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agent-templates',
      expect.objectContaining({
        method: 'POST',
        body: expect.objectContaining({ name: '我的模板', main_model: 'gpt-4o' }),
      }),
    );
    expect(returned.id).toBe(3);
    const list = useTemplatesStore.getState().templates;
    expect(list.some((t) => t.id === 3)).toBe(true);
    expect(useTemplatesStore.getState().error).toBeNull();
  });

  it('createTemplate 失败：rethrow + error 设置 + 列表不变', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(422, '名称已存在'));
    await act(async () => {
      await expect(useTemplatesStore.getState().createTemplate(CREATE_INPUT)).rejects.toThrow('名称已存在');
    });
    const s = useTemplatesStore.getState();
    expect(s.error).toContain('名称已存在');
    expect(s.templates).toEqual([]);
  });

  it('updateTemplate 成功：PATCH /api/v1/agent-templates/{id}（body = patch）→ 列表项以响应为准替换', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    const updated = { ...TEMPLATES[0], name: '经典玄幻改' };
    apiFetchMock.mockResolvedValue(updated);
    await act(async () => {
      await useTemplatesStore.getState().updateTemplate(1, { name: '经典玄幻改' });
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agent-templates/1',
      expect.objectContaining({
        method: 'PATCH',
        body: expect.objectContaining({ name: '经典玄幻改' }),
      }),
    );
    const list = useTemplatesStore.getState().templates;
    expect(list.find((t) => t.id === 1)?.name).toBe('经典玄幻改');
    expect(useTemplatesStore.getState().error).toBeNull();
  });

  it('updateTemplate 失败：rethrow + error 设置 + 列表不变', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    apiFetchMock.mockRejectedValue(new ApiError(500, '保存失败'));
    await act(async () => {
      await expect(useTemplatesStore.getState().updateTemplate(1, { name: 'x' })).rejects.toThrow('保存失败');
    });
    const s = useTemplatesStore.getState();
    expect(s.error).toContain('保存失败');
    expect(s.templates.find((t) => t.id === 1)?.name).toBe('经典玄幻');
  });
});

describe('templates store — 删除 / 复制', () => {
  it('deleteTemplate 成功：DELETE /api/v1/agent-templates/{id} → 从列表移除', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    apiFetchMock.mockResolvedValue({ ok: true });
    await act(async () => {
      await useTemplatesStore.getState().deleteTemplate(1);
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agent-templates/1',
      expect.objectContaining({ method: 'DELETE' }),
    );
    const list = useTemplatesStore.getState().templates;
    expect(list.some((t) => t.id === 1)).toBe(false);
    expect(list.some((t) => t.id === 2)).toBe(true);
  });

  it('deleteTemplate 失败：error + 列表不变（不 rethrow）', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    apiFetchMock.mockRejectedValue(new ApiError(409, '模板被引用'));
    await act(async () => {
      await useTemplatesStore.getState().deleteTemplate(1);
    });
    const s = useTemplatesStore.getState();
    expect(s.error).toContain('模板被引用');
    expect(s.templates).toHaveLength(2);
  });

  it('duplicateTemplate 成功：POST /api/v1/agent-templates/{id}/duplicate → 复制结果追加列表尾部', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    const dup: AgentTemplate = {
      ...TEMPLATES[0],
      id: 3,
      name: '经典玄幻（副本）',
      is_default: false,
      used_by: [],
    };
    apiFetchMock.mockResolvedValue(dup);
    await act(async () => {
      await useTemplatesStore.getState().duplicateTemplate(1);
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agent-templates/1/duplicate',
      expect.objectContaining({ method: 'POST' }),
    );
    const list = useTemplatesStore.getState().templates;
    expect(list.some((t) => t.id === 3)).toBe(true);
    expect(useTemplatesStore.getState().error).toBeNull();
  });
});

describe('templates store — 默认模板', () => {
  it('setDefault 成功：PATCH /api/v1/agent-templates/default（body {id}）→ defaultTemplateId + is_default 翻转', async () => {
    apiFetchMock.mockResolvedValue({ items: TEMPLATES, total: 2, offset: 0, limit: 50 });
    await act(async () => {
      await useTemplatesStore.getState().loadTemplates();
    });
    apiFetchMock.mockResolvedValue({ ok: true });
    await act(async () => {
      await useTemplatesStore.getState().setDefault(2);
    });
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/v1/agent-templates/default',
      expect.objectContaining({ method: 'PATCH', body: expect.objectContaining({ id: 2 }) }),
    );
    const s = useTemplatesStore.getState();
    expect(s.defaultTemplateId).toBe(2);
    expect(s.templates.find((t) => t.id === 2)?.is_default).toBe(true);
    expect(s.templates.find((t) => t.id === 1)?.is_default).toBe(false);
  });

  it('setDefault 失败：error 设置 + defaultTemplateId 不变', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(500, '设置失败'));
    await act(async () => {
      await useTemplatesStore.getState().setDefault(1);
    });
    const s = useTemplatesStore.getState();
    expect(s.error).toContain('设置失败');
    expect(s.defaultTemplateId).toBeNull();
  });

  it('loadDefault 成功：GET /api/v1/agent-templates/default → defaultTemplateId = 响应实体 id', async () => {
    apiFetchMock.mockResolvedValue(TEMPLATES[0]);
    await act(async () => {
      await useTemplatesStore.getState().loadDefault();
    });
    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/agent-templates/default');
    expect(useTemplatesStore.getState().defaultTemplateId).toBe(1);
  });

  it('loadDefault 失败：error 设置（不 rethrow）', async () => {
    apiFetchMock.mockRejectedValue(new ApiError(500, '默认模板不可用'));
    await act(async () => {
      await useTemplatesStore.getState().loadDefault();
    });
    const s = useTemplatesStore.getState();
    expect(s.error).toContain('默认模板不可用');
    expect(s.defaultTemplateId).toBeNull();
  });
});
