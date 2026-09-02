/**
 * e2e-seed.ts buildSeed 结构契约（S3f-T3 R4，contract-s3f-t3 §1.3）。
 *
 * buildSeed(projectName) → SeedContent：固定中文内容；唯一后缀由调用方经 projectName
 * 传入并原样透传（E2E 惯例 `${Date.now()}` 后缀——防共享库同名残留，#167/#366 先例）。
 * 结构不变量（本文件锁定，GREEN 实现须满足）：
 * - characters：3 角色（name/personality 非空，名互异）
 * - worlds：世界观 2 级树 = 恰 1 根 + ≥1 子（子经 parentName 引用根名）
 * - outlines：大纲三级齐备（overall / volume / chapter 各 ≥1，level 即契约值）
 * - volumes：2 卷共 3 章；每章正文 ≥50 字中文
 * - 未挂卷章：恰 1 章 title 含「未挂卷」标记——seedProjectViaApi 落库时该章
 *   volume_id=null（树/导出归「未分组」卷，output_service.py §6.1 语义；
 *   卷2 的挂卷章 order 显式由执行器负责，结构面不锁）
 *
 * 纯 Node 模块（vitest + Playwright 双加载，#415 约束）。
 * RED 形态：e2e-seed.ts 不存在 → vitest Cannot find module（本文件 collection FAIL）。
 */
import { describe, expect, it } from 'vitest';
import { buildSeed, type SeedContent } from './e2e-seed';

describe('buildSeed 结构不变量（S3f-T3 §1.3）', () => {
  it('① projectName 透传（调用方唯一后缀参数生效）+ 固定 3 角色', () => {
    const unique = `E2E-SEED-${Date.now()}`;
    const seed: SeedContent = buildSeed(unique);
    expect(seed.projectName).toBe(unique);
    expect(seed.characters).toHaveLength(3);
    for (const c of seed.characters) {
      expect(c.name.trim().length).toBeGreaterThan(0);
      expect(c.personality.trim().length).toBeGreaterThan(0);
    }
    // 角色名项目内互异（后端项目内唯一约束）
    expect(new Set(seed.characters.map((c) => c.name)).size).toBe(3);
  });

  it('② 世界观 2 级树：恰 1 根 + ≥1 子（parentName 引用根名）', () => {
    const seed = buildSeed(`E2E-SEED-${Date.now()}`);
    const roots = seed.worlds.filter((w) => !w.parentName);
    const children = seed.worlds.filter((w) => w.parentName);
    expect(roots).toHaveLength(1);
    expect(children.length).toBeGreaterThanOrEqual(1);
    const names = new Set(seed.worlds.map((w) => w.name));
    for (const w of seed.worlds) {
      expect(w.content.trim().length).toBeGreaterThan(0);
      expect(w.category.trim().length).toBeGreaterThan(0);
    }
    for (const c of children) {
      expect(names.has(c.parentName as string)).toBe(true);
    }
  });

  it('③ 大纲三级齐备：overall / volume / chapter 各 ≥1', () => {
    const seed = buildSeed(`E2E-SEED-${Date.now()}`);
    const levels = seed.outlines.map((o) => o.level);
    expect(levels).toContain('overall');
    expect(levels).toContain('volume');
    expect(levels).toContain('chapter');
    for (const o of seed.outlines) {
      expect(o.name.trim().length).toBeGreaterThan(0);
    }
  });

  it('④ 2 卷共 3 章，每章正文 ≥50 字', () => {
    const seed = buildSeed(`E2E-SEED-${Date.now()}`);
    expect(seed.volumes).toHaveLength(2);
    const chapters = seed.volumes.flatMap((v) => v.chapters);
    expect(chapters).toHaveLength(3);
    // 每卷 ≥1 章（未挂卷章不独占某卷——见 ⑤）
    for (const v of seed.volumes) {
      expect(v.chapters.length).toBeGreaterThanOrEqual(1);
    }
    expect(new Set(seed.volumes.map((v) => v.title)).size).toBe(2);
    for (const c of chapters) {
      expect(c.title.trim().length).toBeGreaterThan(0);
      expect(c.content.trim().length).toBeGreaterThanOrEqual(50);
    }
  });

  it('⑤ 含恰 1 章未挂卷（title 含「未挂卷」标记 → 执行器 volume_id=null 落「未分组」）', () => {
    const seed = buildSeed(`E2E-SEED-${Date.now()}`);
    const chapters = seed.volumes.flatMap((v) => v.chapters);
    const ungrouped = chapters.filter((c) => c.title.includes('未挂卷'));
    expect(ungrouped).toHaveLength(1);
    // 其余 2 章均为挂卷章（无标记）——2 卷 3 章计数不依赖未挂卷章
    expect(chapters.filter((c) => !c.title.includes('未挂卷'))).toHaveLength(2);
  });
});
