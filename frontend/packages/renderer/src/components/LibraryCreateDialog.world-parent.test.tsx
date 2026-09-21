/**
 * #1322 批 2：地图视图内新建世界观条目须**显式选父**。
 *
 * 后端 #641「parent_id 缺失 → 自动挂项目根」保留（与 #834「一项目一根」耦合，
 * 改后端语义属 spec 级变更，挂 #1666 之前的 #1334）。但前端至少要**表达父级**：
 * 在地图视图（workbenchActive）里新建条目时，带 `initialParentId` → body 含
 * `parent_id`，条目挂到指定父下而**不是**靠后端兜底挂根。
 *
 * 父级来源：地图视图内新建 = 选中分类时的子条目 → 挂**根条目下**（选中分类本身
 * 不是条目，无法作父）。表单不新增父级选择器（YAGNI：工作台内无可选父集合的 UI）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LibraryCreateDialog } from './LibraryCreateDialog';
import { useThemeStore } from '../stores/theme';

beforeEach(() => {
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
});

describe('LibraryCreateDialog — #1322 world 创建带 parent_id', () => {
  it('world 创建传 initialParentId → onSave body 含 parent_id（不落根）', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <LibraryCreateDialog
        open
        cat="world"
        isRoot={false}
        initialCategory="国家"
        initialParentId="w-root"
        onSave={onSave}
        onOpenChange={vi.fn()}
      />,
    );
    await user.type(screen.getByTestId('library-create-name'), '青云山');
    await user.click(screen.getByTestId('library-create-save'));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0][0]).toMatchObject({
      name: '青云山',
      category: '国家',
      parent_id: 'w-root',
    });
  });

  it('未传 initialParentId → parent_id 为 null（后端 #641 自动挂根兜底不变）', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <LibraryCreateDialog
        open
        cat="world"
        isRoot={false}
        initialCategory="国家"
        onSave={onSave}
        onOpenChange={vi.fn()}
      />,
    );
    await user.type(screen.getByTestId('library-create-name'), '青云山');
    await user.click(screen.getByTestId('library-create-save'));

    expect(onSave.mock.calls[0][0]).toMatchObject({ parent_id: null });
  });
});
