/**
 * 项目卡片 ProjectCard 测试契约（#595 D7=A / #596 回归护栏）——标签展示。
 *
 * ⚠️ 本文件 = 契约。GREEN 实现 components/ProjectCard.tsx 必须匹配（specs/f1-project/spec.md §2.1）：
 * - 有标签：卡片展示 tags 全拼（`tags.join('，')` 逗号分隔，保序）
 * - 空标签：不渲染标签行（`project.tags.length > 0` 守卫）
 *
 * 由于 #595 已实现 ProjectCard.tsx（GREEN），本文件为**已交付功能回归测试**；
 * 全部用例应即时 PASS（非 RED→GREEN 新功能）。
 * 其余卡片行为（进度条/相对时间/菜单/点击跳转）已在 projects.test.tsx 页级覆盖，不在此重复。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ProjectCard } from './ProjectCard';
import { useThemeStore } from '../stores/theme';
import type { Project } from '../stores/project';

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'p1',
    name: '青云志',
    tags: [],
    language: 'zh-CN',
    target_words: 0,
    config: {},
    created_at: '2026-08-01T10:00:00Z',
    updated_at: new Date(Date.now() - 30_000).toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  // useI18n 读 theme store lang；默认 zh
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('项目卡片 ProjectCard — 标签展示（#595 D7=A / #596）', () => {
  it('有标签：卡片展示 tags 全拼（逗号分隔）', () => {
    render(<ProjectCard project={makeProject({ tags: ['玄幻', '热血'] })} isCurrent={false} />);
    const card = screen.getByTestId('project-card');
    expect(card).toHaveTextContent('玄幻，热血');
  });

  it('多标签：join 保留全部且保序', () => {
    render(
      <ProjectCard project={makeProject({ tags: ['修真', '热血', '升级流'] })} isCurrent={false} />,
    );
    const card = screen.getByTestId('project-card');
    expect(card).toHaveTextContent('修真，热血，升级流');
  });

  it('空标签：不渲染标签行（target_words=0 防止 toLocaleString 逗号干扰断言）', () => {
    render(<ProjectCard project={makeProject({ tags: [], target_words: 0 })} isCurrent={false} />);
    const card = screen.getByTestId('project-card');
    expect(card).toHaveTextContent('青云志');
    expect(card.textContent).not.toContain('玄幻');
    expect(card.textContent).not.toContain('，'); // 无标签行（0 → '0' 无逗号）
  });
});

/**
 * 项目导出（RED 阶段契约，GREEN 未实现）：
 * - ProjectCard 新增 prop onExport?: (project: Project) => void
 * - 卡片 ⋯ 菜单打开 → 菜单项 data-testid=`project-export-${project.id}`（文案「导出」）
 * - 点击导出菜单项 → onExport(project) 恰好调用一次
 *
 * RED 预期：onExport/导出菜单项未实现 → project-export-* 缺失 → 本 describe FAIL。
 */
describe('项目卡片菜单 — 导出', () => {
  it('菜单打开后出现「导出」菜单项', async () => {
    const user = userEvent.setup();
    const project = makeProject();
    render(<ProjectCard project={project} isCurrent={false} />);

    await user.click(screen.getByTestId(`project-card-menu-${project.id}`));

    const exportItem = screen.getByTestId(`project-export-${project.id}`);
    expect(exportItem).toHaveTextContent('导出');
  });

  it('点击「导出」菜单项 → onExport 以 project 被调用一次', async () => {
    const user = userEvent.setup();
    const project = makeProject();
    const onExport = vi.fn();
    render(<ProjectCard project={project} isCurrent={false} onExport={onExport} />);

    await user.click(screen.getByTestId(`project-card-menu-${project.id}`));
    await user.click(screen.getByTestId(`project-export-${project.id}`));

    expect(onExport).toHaveBeenCalledTimes(1);
    expect(onExport).toHaveBeenCalledWith(project);
  });
});
