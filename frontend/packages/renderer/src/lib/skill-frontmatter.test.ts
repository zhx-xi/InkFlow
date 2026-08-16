/**
 * ⚠️ 契约文件（F40 #259 skill 上传 RED 阶段，spec §2.2 frontmatter 契约 + §5.4 上传预览）
 *
 * GREEN 新建 src/lib/skill-frontmatter.ts，必须匹配：
 *
 * 导出：
 * - parseSkillFrontmatter(content: string): SkillFrontmatter
 *   解析 SKILL.md frontmatter（镜像后端 skill_service._parse_frontmatter 规则）：
 *   - 首行必须为 ---（trim 后），缺 → 抛 SkillFrontmatterError
 *   - 逐行解析 key: value（跳过空行/注释行），遇闭合 --- 结束；未闭合 → 抛 SkillFrontmatterError
 *   - name 必填且匹配 ^[a-z0-9-]{1,64}$（小写字母数字+连字符）；description 必填
 *   - name/description 缺失或 name 非法 → 抛 SkillFrontmatterError（含中文提示）
 * - SkillFrontmatter = { name: string; description: string; tags: string[] }
 *   （tags 可选：frontmatter tags 行逗号分隔解析为数组；无 tags 行 → []）
 * - SkillFrontmatterError（class，含 message 字段；message 可直接展示）
 *
 * 契约锚点：spec §2.2「frontmatter 契约（F40 上传解析）」：name（必选，1-64 小写字母数字+连字符）、
 * description（必选）、tags（可选，列表，本 spec 不落列、保留在 content frontmatter 内）。
 * 错误语义对齐后端 §7-②：缺失/非法 → 422 类提示（预览阶段前端直接提示，不调后端）。
 *
 * RED 预期：./skill-frontmatter 模块不存在 → module-not-found（类 1 契约缺口，suite 级失败）。
 */
import { describe, it, expect } from 'vitest';
import { parseSkillFrontmatter, SkillFrontmatterError } from './skill-frontmatter';

const VALID = `---
name: web-research
description: 网络调研方法论
tags: research, web
---
# 调研流程
1. 明确问题`;

describe('parseSkillFrontmatter — 合法解析', () => {
  it('解析 name/description/tags + 忽略正文', () => {
    const fm = parseSkillFrontmatter(VALID);
    expect(fm.name).toBe('web-research');
    expect(fm.description).toBe('网络调研方法论');
    expect(fm.tags).toEqual(['research', 'web']);
  });

  it('无 tags 行 → tags=[]', () => {
    const fm = parseSkillFrontmatter(`---
name: plain
description: 无标签
---
正文`);
    expect(fm.tags).toEqual([]);
  });

  it('值为空字符串 / 引号包裹 → 去引号解析（镜像后端 strip 语义）', () => {
    const fm = parseSkillFrontmatter(`---
name: "quoted-name"
description: '带引号描述'
---
正文`);
    expect(fm.name).toBe('quoted-name');
    expect(fm.description).toBe('带引号描述');
  });
});

describe('parseSkillFrontmatter — 非法输入', () => {
  it('首行非 --- → 抛错', () => {
    expect(() => parseSkillFrontmatter('name: x\ndescription: y\n---\n正文')).toThrow(
      SkillFrontmatterError
    );
  });

  it('frontmatter 未闭合 → 抛错', () => {
    expect(() =>
      parseSkillFrontmatter(`---
name: x
description: y
正文未闭合`)
    ).toThrow(SkillFrontmatterError);
  });

  it('name 缺失 → 抛错', () => {
    expect(() =>
      parseSkillFrontmatter(`---
description: 只有描述
---
正文`)
    ).toThrow(SkillFrontmatterError);
  });

  it('description 缺失 → 抛错', () => {
    expect(() =>
      parseSkillFrontmatter(`---
name: ok-name
---
正文`)
    ).toThrow(SkillFrontmatterError);
  });

  it('name 含大写字母 → 抛错（^[a-z0-9-]{1,64}$）', () => {
    expect(() =>
      parseSkillFrontmatter(`---
name: Web-Research
description: 大写非法
---
正文`)
    ).toThrow(SkillFrontmatterError);
  });

  it('name 含中文 → 抛错', () => {
    expect(() =>
      parseSkillFrontmatter(`---
name: 调研方法论
description: 中文非法
---
正文`)
    ).toThrow(SkillFrontmatterError);
  });

  it('name 超 64 字符 → 抛错', () => {
    const long = 'a'.repeat(65);
    expect(() =>
      parseSkillFrontmatter(`---
name: ${long}
description: 超长非法
---
正文`)
    ).toThrow(SkillFrontmatterError);
  });

  it('错误 message 为可展示中文（非空字符串）', () => {
    try {
      parseSkillFrontmatter('not-frontmatter');
      expect.unreachable('应抛错');
    } catch (err) {
      expect(err).toBeInstanceOf(SkillFrontmatterError);
      expect((err as Error).message.length).toBeGreaterThan(0);
    }
  });
});
