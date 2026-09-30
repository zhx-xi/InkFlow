/**
 * #1373 知识图谱「节点个体着色」纯函数（方案 A：类型色相带内按 hash 派生 3 色相 × 2 明度）
 * 对应 specs/f19-gui/knowledge.md §4.1 + 验收 N10
 *
 * 纯函数契约：同 `id|name` 的实体在任意会话 / 任意批次中都得到完全相同的色值
 * （不得使用随机数、时间、模块级可变缓存、数组下标或其它节点信息）。
 *
 * 🔴 色值一律写成逗号分隔形态 `hsl(346, 66%, 96%)`：jsdom / cssstyle 不支持 CSS Color 4
 *    的空格形态（`hsl(346 66% 96%)`）会把整条内联样式声明丢弃，而浏览器两种写法渲染等价。
 *
 * 🔴 色相三档必须是**对称**的 «基准 −18° / 基准 / 基准 +18°»（拍板色带，span 36°）。
 *    不得改成 «0 / +9 / −18» 之类的非对称档去迁就任何测试写法。
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

/** 按 `id|name` 派生个体色板：类型色相带内 3 档（基准 −18° / 基准 / 基准 +18°）× 2 档明度 */
export function deriveNodeColor(node: { id: string; name: string; type: EntityType }): KgPalette {
  const h = hash32(`${node.id}|${node.name}`);
  const hue = TYPE_HUE[node.type] + ((h % 3) - 1) * 18;
  const dark = Math.floor(h / 3) % 2 === 1;
  return {
    dot: `hsl(${norm(hue)}, 66%, ${dark ? 42 : 58}%)`,
    border: `hsl(${norm(hue)}, 56%, ${dark ? 66 : 82}%)`,
    bg: `hsl(${norm(hue)}, 70%, ${dark ? 88 : 96}%)`,
    text: `hsl(${norm(hue)}, 62%, ${dark ? 24 : 34}%)`,
  };
}
