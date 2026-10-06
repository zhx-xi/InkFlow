/**
 * #1494：世界观页首开语义文案域（从 zh.ts / en.ts 拆出以守 900 行护栏，同 world-cat-kind.ts 先例）。
 *
 * - `lib.world.rootTitle`：**默认根**的本地化标题（D3c）。前端按**结构判据 isRoot**
 *   （`parent_id` 为空且 `category` 为空）渲染此文案，**不做 name 匹配** → 根改名后本地化仍生效。
 *   后端默认根名常量 `DEFAULT_WORLD_ROOT_NAME`（`世界观总纲`）保持不动，本域不改后端。
 * - `lib.world.firstOpen.hint*`：首开（根无子条目）时根下引导行文案，`{name}` = 上述本地化标题。
 *   零分类走 hintNoCategory（CTA 引导先建分类），已有分类走 hint（CTA 建子条目）。
 */
export const worldFirstOpenZh: Record<string, string> = {
  'lib.world.rootTitle': '世界观总纲',
  'lib.world.firstOpen.hint': '还没有条目 — 在{name}下新建条目',
  'lib.world.firstOpen.hintNoCategory': '还没有条目 — 先新建一个分类，再在{name}下添加条目',
};

export const worldFirstOpenEn: Record<string, string> = {
  'lib.world.rootTitle': 'World Overview',
  'lib.world.firstOpen.hint': 'No entries yet — add entries under {name}',
  'lib.world.firstOpen.hintNoCategory':
    'No entries yet — create a category first, then add entries under {name}',
};
