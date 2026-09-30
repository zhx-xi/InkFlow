/**
 * #1373 知识图谱「节点个体着色」RED 契约（unit 层，纯函数）
 * 对应 specs/f19-gui/knowledge.md §4.1（方案 A）+ 验收 N10
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【本次要证明的命题（一句话）】
 * 同类型多实体在画布上「肉眼可辨」（类型色相带内按 hash 派生 3 色相 × 2 明度），
 * 且同一实体跨会话/跨刷新恒得同色（纯函数，无随机数、无兄弟节点依赖）。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（2026-09-30，不得改方案）】
 * - 方案 A（采用）：`hue = TYPE_HUE[type] + ((h % 3) - 1) * 18`；`dark = floor(h / 3) % 2 === 1`
 *   （`h = FNV-1a 32(hash)`，`TYPE_HUE = character 4 / world 217 / outline 142 /
 *   timeline 45 / foreshadow 262 / map_pin 25`）
 * - 🔴 判据 = **最大单通道差 ≥ 40**（不是「rgb 字符串不等」）——原型首跑实测：
 *   初版 ±13°/6% 亮度在真实渲染下 8 个角色看起来仍是一个色，故校准为 ±18°/14% 亮度。
 *   （判据与 design/GUI/_tools/shot-knowledge-graph-scope.cjs 的 `typeColorSpread()` 同源）
 * - 方案 B（图邻接贪心着色）**不实现**（颜色随图结构变化 → 不跨会话稳定）
 *
 * 【RED 预期】本文件在实现前必须真跑起来并 FAIL（非 collection error）：
 *   `kgColor` 模块不存在 → 文件级 `Failed to resolve import "./kgColor"`（1 个 Failed Suite）
 */
import { describe, it, expect } from 'vitest';
import { TYPE_HUE, deriveNodeColor, hash32, typeBaseDot } from './kgColor';
import type { EntityType, GraphNode } from '../../api/knowledge-graph';

/** 六类实体（与 specs/f48-knowledge-graph/spec.md §2.1 规则 1 对齐） */
const ENTITY_TYPES: EntityType[] = ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin'];

/** `hsl(H, S%, L%)` → [h, s, l]；形态不符 → null（形态本身即契约的一部分）
 *
 *  🔴 记法必须是**逗号分隔**（`hsl(346, 66%, 96%)`）——#1373 实测：
 *  jsdom / cssstyle 不支持 CSS Color 4 的空格分隔形态（`hsl(346 66% 96%)` / `rgb(254 226 226)`）
 *  → **整条声明被丢弃**（`el.getAttribute('style')` 为 null、`el.style.backgroundColor` 为空串），
 *  而浏览器两种写法渲染等价。取逗号形 = 浏览器渲染一致 + jsdom 可断言（否则着色契约无法在集成层验证）。
 */
function parseHsl(value: string): [number, number, number] | null {
  const m = /^hsl\((\d+), (\d+)%, (\d+)%\)$/.exec(value);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

/** hsl → rgb（0-255）。测试侧换算，用于「肉眼可辨」判据（不做 CSS 求值，避免 jsdom 差异） */
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const hh = ((h % 360) + 360) % 360;
  const ss = s / 100;
  const ll = l / 100;
  const c = (1 - Math.abs(2 * ll - 1)) * ss;
  const x = c * (1 - Math.abs(((hh / 60) % 2) - 1));
  const m = ll - c / 2;
  let rgb: [number, number, number];
  if (hh < 60) rgb = [c, x, 0];
  else if (hh < 120) rgb = [x, c, 0];
  else if (hh < 180) rgb = [0, c, x];
  else if (hh < 240) rgb = [0, x, c];
  else if (hh < 300) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  return rgb.map((v) => Math.round((v + m) * 255)) as [number, number, number];
}

function rgbOf(value: string): [number, number, number] {
  const hsl = parseHsl(value);
  expect(hsl, `色值形态必须为 hsl(H S% L%)：实际 ${value}`).not.toBeNull();
  const [h, s, l] = hsl as [number, number, number];
  return hslToRgb(h, s, l);
}

/** 两色最大单通道差（0-255）——与原型 shot 脚本 `maxChannelDelta` 同口径 */
function maxChannelDelta(a: string, b: string): number {
  const x = rgbOf(a);
  const y = rgbOf(b);
  return Math.max(Math.abs(x[0] - y[0]), Math.abs(x[1] - y[1]), Math.abs(x[2] - y[2]));
}

/** 色相环上到基准色相的最短距离（处理 346° 与 4° 这类跨 0 环绕） */
function hueDistance(hue: number, base: number): number {
  const d = Math.abs(hue - base) % 360;
  return Math.min(d, 360 - d);
}

/** 归一化色相 → 相对基准色相的**有符号**偏移（度，值域 (-180, 180]）。
 *  🔴 与 hueDistance 的区别是关键：对称三档 «−18 / 0 / +18» 的**环距离**只有 {0,18} 两档
 *  （−18 与 +18 到基准的距离都是 18），故判「是否 3 档」必须用有符号偏移，不能用环距离。
 *  （#1373 实测教训：用环距离判 3 档 → 契约把实现逼去改拍板色带，见 PR 说明。） */
function signedHueOffset(hue: number, base: number): number {
  return ((hue - base + 540) % 360) - 180;
}

function node(id: string, name: string, type: EntityType): GraphNode {
  return { id, type, entity_id: id.split(':')[1] ?? id, name };
}

describe('#1373 节点个体着色（方案 A：hash 派生 3 色相 × 2 明度）', () => {
  // ── 1. hash 稳定性（稳定性的唯一来源）────────────────────────────
  it('hash32：FNV-1a 32 位（已知向量恒定，非随机/非时间相关）', () => {
    // 任一非 FNV-1a 实现（如 djb2 / 简单位移）必然在这些向量上 FAIL
    expect(hash32('')).toBe(2166136261);
    expect(hash32('a')).toBe(3826002220);
    expect(hash32('foobar')).toBe(3214735720);
    // 同输入恒定（多次调用逐位相同）
    expect(hash32('character:c1|角色甲')).toBe(hash32('character:c1|角色甲'));
  });

  // ── 2. 纯函数：同实体恒得同色，且与兄弟节点/渲染次序无关 ──────────
  it('N10 纯函数：同一 name|id 两次派生逐字段相同，且与「同批其他节点」无关', () => {
    const target = node('character:c1', '角色甲', 'character');

    const solo = deriveNodeColor(target);
    const again = deriveNodeColor(target);
    expect(again).toEqual(solo);
    // 与批次内其它节点无关：先派生一批兄弟，再重算目标 → 仍逐字段相同
    deriveNodeColor(node('character:c9', '角色癸', 'character'));
    deriveNodeColor(node('world:w9', '地点癸', 'world'));
    const withSiblings = deriveNodeColor(target);
    expect(withSiblings).toEqual(solo);
    expect(withSiblings.dot).toBe(solo.dot);
    expect(withSiblings.bg).toBe(solo.bg);
    expect(withSiblings.border).toBe(solo.border);
    expect(withSiblings.text).toBe(solo.text);
  });

  // ── 3. 色板形态：hsl(H S% L%) 且明度两档（3 色相 × 2 明度）─────────
  it('N10 色板形态：四通道均为 hsl(H, S%, L%)（逗号记法），明度两档（2 明度）', () => {
    for (const t of ENTITY_TYPES) {
      const c = deriveNodeColor(node(`${t}:x1`, `样例-${t}`, t));
      const dot = parseHsl(c.dot);
      const border = parseHsl(c.border);
      const bg = parseHsl(c.bg);
      const text = parseHsl(c.text);
      expect(dot, `dot 形态 ${c.dot}`).not.toBeNull();
      expect(border, `border 形态 ${c.border}`).not.toBeNull();
      expect(bg, `bg 形态 ${c.bg}`).not.toBeNull();
      expect(text, `text 形态 ${c.text}`).not.toBeNull();
      // 明度两档：圆点 58%/42%、底色 96%/88%（原型校准值）
      expect([58, 42]).toContain((dot as [number, number, number])[2]);
      expect([96, 88]).toContain((bg as [number, number, number])[2]);
    }
  });

  it('N10 色相带：3 档偏移必须恰为 基准 −18 / 0 / +18（拍板色带，span=36°）', () => {
    for (const t of ENTITY_TYPES) {
      const offsets = new Set<number>();
      for (let i = 0; i < 60; i += 1) {
        const c = deriveNodeColor(node(`${t}:n${i}`, `实体${i}`, t));
        const dot = parseHsl(c.dot) as [number, number, number];
        // 色环距离 ≤ 18°（跨 0° 环绕也算）
        expect(hueDistance(dot[0], TYPE_HUE[t])).toBeLessThanOrEqual(18);
        offsets.add(signedHueOffset(dot[0], TYPE_HUE[t]));
      }
      // 60 个样本必须命中「−18 / 0 / +18」三档（证明是基准色带内派生，而非固定单色）
      expect([...offsets].sort((a, b) => a - b), `${t} 色相偏移档`).toEqual([-18, 0, 18]);
    }
  });

  // ── 4. 个体可辨（N10 的核心判据）─────────────────────────────────
  it('N10 同类型 8 实体：最大单通道差 ≥ 40（肉眼可辨，非「rgb 字符串不等」）', () => {
    const names = ['角色甲', '角色乙', '角色丙', '角色丁', '角色戊', '角色己', '角色庚', '角色辛'];
    const chars = names.map((n, i) => node(`character:c${i + 1}`, n, 'character'));

    let maxDot = 0;
    let maxBg = 0;
    const distinctDots = new Set<string>();
    for (let i = 0; i < chars.length; i += 1) {
      const a = deriveNodeColor(chars[i]);
      distinctDots.add(a.dot);
      for (let j = i + 1; j < chars.length; j += 1) {
        const b = deriveNodeColor(chars[j]);
        maxDot = Math.max(maxDot, maxChannelDelta(a.dot, b.dot));
        maxBg = Math.max(maxBg, maxChannelDelta(a.bg, b.bg));
      }
    }
    // 判据与原型 shot 脚本一致：dot 差 ≥ 40 或 bg 差 ≥ 30
    expect(maxDot >= 40 || maxBg >= 30, `maxDot=${maxDot} maxBg=${maxBg}`).toBe(true);
    expect(distinctDots.size).toBeGreaterThan(1);
  });

  it('N10 跨会话稳定：重放 12 次（中间穿插其它实体派生）逐字段相同', () => {
    const target = node('character:c1', '角色甲', 'character');
    const baseline = deriveNodeColor(target);
    for (let i = 0; i < 12; i += 1) {
      // 穿插其它实体的派生（捕捉「模块级缓存 / 上次结果复用」类实现缺陷）
      deriveNodeColor(node(`world:w${i}`, `地点${i}`, 'world'));
      deriveNodeColor(node(`character:c${i + 2}`, `角色${i}`, 'character'));
      expect(deriveNodeColor(target)).toEqual(baseline);
    }
  });

  // ── 5. 类型可辨（图例基准色）──────────────────────────────────
  it('N10 图例基准色：六类基准圆点两两最大单通道差 ≥ 40（类型一眼可辨）', () => {
    for (let i = 0; i < ENTITY_TYPES.length; i += 1) {
      for (let j = i + 1; j < ENTITY_TYPES.length; j += 1) {
        const a = typeBaseDot(ENTITY_TYPES[i]);
        const b = typeBaseDot(ENTITY_TYPES[j]);
        expect(maxChannelDelta(a, b), `${ENTITY_TYPES[i]} vs ${ENTITY_TYPES[j]}`).toBeGreaterThanOrEqual(40);
      }
    }
    // 基准圆点恒等同类型常数值（图例不随实体波动）
    expect(typeBaseDot('character')).toBe(typeBaseDot('character'));
  });
});
