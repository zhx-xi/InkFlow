/**
 * #1373 / #1418 知识图谱「节点个体着色」纯函数
 * （方案 A：类型色相带内按 hash 派生 4 色相 × 3 明度 = 12 色槽）
 * 对应 specs/f19-gui/knowledge.md §4.1 + 验收 N10
 *
 * 纯函数契约：同 `id|name` 的实体在任意会话 / 任意批次中都得到完全相同的色值
 * （不得使用随机数、时间、模块级可变缓存、数组下标或其它节点信息）。
 *
 * 🔴 色值一律写成逗号分隔形态 `hsl(346, 66%, 96%)`：jsdom / cssstyle 不支持 CSS Color 4
 *    的空格形态（`hsl(346 66% 96%)`）会把整条内联样式声明丢弃，而浏览器两种写法渲染等价。
 *
 * 🔴 色相四档必须是**对称**的 «基准 −18° / 基准 −6° / 基准 +6° / 基准 +18°»（拍板色带，span 36°）。
 *    不得改成 «0 / +9 / −18» 之类的非对称档去迁就任何测试写法。
 *
 * 🔴 #1418 扩槽（6 槽 → 12 槽）：6 槽下 8 个同类型实体实染只有 4 色（碰撞组 3+3，同槽完全同色）
 *    → 原始诉求「节点一多就无法分辨谁是谁」只被部分解决。改 4 色相 × 3 明度后 8 个角色实渲 7 色。
 *
 * 🔴 槽位必须取自**位混匀后**的 hash：FNV-1a 最低位质量差——直接 `h % 4` 在 240 个样本上
 *    只命中 2 个取值（bit0 恒 0）→ 名义 12 槽实际只有 6 槽可达。故先
 *    `imul(h ^ (h >>> 16), 2654435761)` 再取位段（色相 `>>> 4`、明度 `>>> 2`）。不得改回裸 `h % 4`。
 */
import type { EntityType } from '../../api/knowledge-graph';

/** 六类实体基准色相（spec §4.1 方案 A 拍板值；顺序与数值不可改） */
export const TYPE_HUE: Record<EntityType, number> = {
  character: 4,
  world: 217,
  outline: 142,
  timeline: 45,
  foreshadow: 262,
  map_pin: 25,
};

/** 4 色相档偏移（相对类型基准色相，度）：−18 / −6 / +6 / +18 —— 拍板色带 span 36° */
const HUE_OFFSETS = [-18, -6, 6, 18];

/** 3 明度档（亮 / 中 / 暗）：圆点 / 描边 / 底色 / 文字 L%（步长 10% → 同色相相邻档色差 ≥ 40） */
const LIGHT_STEPS = [
  { dot: 60, border: 82, bg: 96, text: 34 },
  { dot: 50, border: 74, bg: 92, text: 29 },
  { dot: 40, border: 66, bg: 88, text: 24 },
];

/** 节点色板（圆点 / 描边 / 底色 / 文字四通道，均为 `hsl(H, S%, L%)` 逗号记法） */
export interface KgPalette {
  dot: string;
  border: string;
  bg: string;
  text: string;
}

/** FNV-1a 32 位哈希（稳定性的唯一来源）：返回无符号 32 位整数 */
export function hash32(str: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

/** 色相规整到 [0, 360)：`((h % 360) + 360) % 360` */
function norm(h: number): number {
  return ((h % 360) + 360) % 360;
}

/** 类型基准圆点色（图例用；同类型恒等同值，不随实体波动） */
export function typeBaseDot(type: EntityType): string {
  return `hsl(${TYPE_HUE[type]}, 62%, 50%)`;
}

/** 按 `id|name` 派生个体色板：类型色相带内 4 档（−18 / −6 / +6 / +18）× 3 档明度 = 12 色槽 */
export function deriveNodeColor(node: { id: string; name: string; type: EntityType }): KgPalette {
  const h = hash32(`${node.id}|${node.name}`);
  /* 位混匀（必需）：FNV-1a 低位质量差，裸取 `h % 4` 会让 12 槽塌缩成 6 槽 */
  const mixed = Math.imul(h ^ (h >>> 16), 2654435761) >>> 0;
  const hue = norm(TYPE_HUE[node.type] + HUE_OFFSETS[(mixed >>> 4) % 4]);
  const step = LIGHT_STEPS[(mixed >>> 2) % 3];
  return {
    dot: `hsl(${hue}, 66%, ${step.dot}%)`,
    border: `hsl(${hue}, 56%, ${step.border}%)`,
    bg: `hsl(${hue}, 70%, ${step.bg}%)`,
    text: `hsl(${hue}, 62%, ${step.text}%)`,
  };
}
