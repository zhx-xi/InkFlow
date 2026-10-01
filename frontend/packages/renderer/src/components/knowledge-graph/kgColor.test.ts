/**
 * #1373 / #1418 知识图谱「节点个体着色」RED 契约（unit 层，纯函数）
 * 对应 specs/f19-gui/knowledge.md §4.1（方案 A）+ 验收 N10
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 【本次要证明的命题（一句话）】
 * 同类型多实体在画布上「肉眼可辨」——类型色相带内按 hash 派生 4 色相 × 3 明度（12 槽），
 * 且同一实体跨会话/跨刷新恒得同色（纯函数，无随机数、无兄弟节点依赖）。
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * 【拍板口径（#1373 定方案 A；#1418 扩槽）】
 * - 方案 A（采用）：色相 = 类型基准色相 + 4 档偏移 «−18 / −6 / +6 / +18»；明度 = 3 档。
 *   （h = FNV-1a 32(id|name)；TYPE_HUE = character 4 / world 217 / outline 142 /
 *   timeline 45 / foreshadow 262 / map_pin 25）
 * - 🔴 判据 = **最大单通道差 ≥ 40**（不是「rgb 字符串不等」）——原型首跑实测：
 *   初版 ±13°/6% 亮度在真实渲染下 8 个角色看起来仍是一个色，故校准为 ±18°/14% 亮度。
 *   （判据与 design/GUI/_tools/shot-knowledge-graph-scope.cjs 的 `typeColorSpread()` 同源）
 * - 🔴 #1418 扩槽理由（6 槽 → 12 槽）：6 槽下 8 个同类型实体**实染只有 4 色**（碰撞组 3+3，
 *   同槽完全同色、最大单通道差 0）→ 原始诉求「节点一多就无法分辨谁是谁」只被部分解决。
 * - 🔴 槽位必须取自**位混匀后**的 hash：FNV-1a 最低位质量差——`h % 4` 在 240 个样本上
 *   只命中 2 个取值（bit0 恒 0）→ 名义 12 槽实际只有 6 槽可达。本文件「12 槽可达」一条即为此设。
 * - 方案 B（图邻接贪心着色）**不实现**（颜色随图结构变化 → 不跨会话稳定）
 */
import { describe, it, expect } from 'vitest';
import { TYPE_HUE, deriveNodeColor, hash32, typeBaseDot } from './kgColor';
import type { EntityType, GraphNode } from '../../api/knowledge-graph';

/** 六类实体（与 specs/f48-knowledge-graph/spec.md §2.1 规则 1 对齐） */
const ENTITY_TYPES: EntityType[] = ['character', 'world', 'outline', 'timeline', 'foreshadow', 'map_pin'];

/** 4 色相档：相对类型基准色相的偏移（度）——拍板色带 span 36° */
const HUE_OFFSETS = [-18, -6, 6, 18];
/** 3 明度档：圆点 L%（亮 / 中 / 暗） */
const DOT_LIGHTNESS = [60, 50, 40];
/** 3 明度档：节点底色 L% */
const BG_LIGHTNESS = [96, 92, 88];

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
  expect(hsl, `色值形态必须为 hsl(H, S%, L%)：实际 ${value}`).not.toBeNull();
  const [h, s, l] = hsl as [number, number, number];
  return hslToRgb(h, s, l);
}

/** 两色最大单通道差（0-255）——与原型 shot 脚本 `maxChannelDelta` 同口径 */
function maxChannelDelta(a: string, b: string): number {
  const x = rgbOf(a);
  const y = rgbOf(b);
  return Math.max(Math.abs(x[0] - y[0]), Math.abs(x[1] - y[1]), Math.abs(x[2] - y[2]));
}

/** 归一化色相 → 相对基准色相的**有符号**偏移（度，值域 (-180, 180]）。
 *  🔴 与环距离的区别是关键：对称多档 «−18 / −6 / +6 / +18» 的**环距离**只有 {6, 18} 等更少取值，
 *  故判「是否恰为这 4 档」必须用有符号偏移，不能用环距离。
 *  （#1373 实测教训：用环距离判档 → 契约把实现逼去改拍板色带，见 PR 说明。） */
function signedHueOffset(hue: number, base: number): number {
  return ((hue - base + 540) % 360) - 180;
}

/** 从派生色板还原「色槽」标识 = 有符号色相偏移 / 圆点明度档（独立于实现细节，仅用色值反推） */
function slotOf(dot: string, base: number): string {
  const [h, , l] = parseHsl(dot) as [number, number, number];
  return `${signedHueOffset(h, base)}/${l}`;
}

function node(id: string, name: string, type: EntityType): GraphNode {
  return { id, type, entity_id: id.split(':')[1] ?? id, name };
}

/** 单测样本：8 个同类型实体（通用占位名，对应 #1373/#1418 的「8 角色实测」口径） */
const EIGHT_NAMES = ['角色甲', '角色乙', '角色丙', '角色丁', '角色戊', '角色己', '角色庚', '角色辛'];
const EIGHT_CHARS = EIGHT_NAMES.map((n, i) => node(`character:c${i + 1}`, n, 'character'));

describe('#1418 节点个体着色（方案 A 扩槽：hash 派生 4 色相 × 3 明度）', () => {
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
  it('N10 纯函数：同一 id|name 两次派生逐字段相同，且与「同批其他节点」无关', () => {
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

  // ── 3. 色板形态：hsl(H, S%, L%) 且明度三档（4 色相 × 3 明度）───────
  it('N10 色板形态：四通道均为 hsl(H, S%, L%)（逗号记法），明度三档', () => {
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
      // 明度三档：圆点 60%/50%/40%、底色 96%/92%/88%（扩槽后按「最大单通道差 ≥ 40」校准入档）
      expect(DOT_LIGHTNESS, `dot 明度 ${c.dot}`).toContain((dot as [number, number, number])[2]);
      expect(BG_LIGHTNESS, `bg 明度 ${c.bg}`).toContain((bg as [number, number, number])[2]);
    }
  });

  // ── 4. 色相带：4 档且锁在基准 ±18° 内 ────────────────────────────
  it('N10 色相带：4 档偏移必须恰为 −18 / −6 / +6 / +18（拍板色带，span=36°）', () => {
    for (const t of ENTITY_TYPES) {
      const offsets = new Set<number>();
      for (let i = 0; i < 240; i += 1) {
        const c = deriveNodeColor(node(`${t}:n${i}`, `实体${i}`, t));
        const dot = parseHsl(c.dot) as [number, number, number];
        // 有符号偏移必须落在四档之一
        expect(HUE_OFFSETS, `${t} 偏移 ${signedHueOffset(dot[0], TYPE_HUE[t])}`).toContain(
          signedHueOffset(dot[0], TYPE_HUE[t]),
        );
        offsets.add(signedHueOffset(dot[0], TYPE_HUE[t]));
      }
      expect([...offsets].sort((a, b) => a - b), `${t} 色相偏移档`).toEqual(HUE_OFFSETS);
    }
  });

  // ── 5. 明度维度自身可辨（否则「同色相跨明度档」= 换了个数字而已）─────
  it('N10 明度三档自身可辨：同一色相档内三档圆点两两最大单通道差 ≥ 40', () => {
    for (const t of ENTITY_TYPES) {
      const byOffset = new Map<number, Map<number, string>>();
      for (let i = 0; i < 240; i += 1) {
        const c = deriveNodeColor(node(`${t}:n${i}`, `实体${i}`, t));
        const [h, , l] = parseHsl(c.dot) as [number, number, number];
        const off = signedHueOffset(h, TYPE_HUE[t]);
        if (!byOffset.has(off)) byOffset.set(off, new Map());
        byOffset.get(off)?.set(l, c.dot);
      }
      expect(byOffset.size, `${t} 实际用到的色相档数`).toBe(4);
      for (const [off, byLight] of byOffset) {
        expect([...byLight.keys()].sort((a, b) => a - b), `${t} 偏移 ${off} 的明度档`).toEqual(
          [...DOT_LIGHTNESS].sort((a, b) => a - b),
        );
        const dots = [...byLight.values()];
        for (let i = 0; i < dots.length; i += 1) {
          for (let j = i + 1; j < dots.length; j += 1) {
            const delta = maxChannelDelta(dots[i], dots[j]);
            expect(delta, `${t} 同色相不同明度 ${dots[i]} vs ${dots[j]} → ${delta}`).toBeGreaterThanOrEqual(40);
          }
        }
      }
    }
  });

  // ── 6. 12 槽可达（防「名义 12 槽、实际低位偏斜只用到 6 槽」）─────────
  it('N10 12 槽全部可达：240 个样本必须命中 4 色相 × 3 明度 = 12 个色槽', () => {
    for (const t of ['character', 'world'] as EntityType[]) {
      const slots = new Set<string>();
      for (let i = 0; i < 240; i += 1) {
        const c = deriveNodeColor(node(`${t}:s${i}`, `实体${i}`, t));
        slots.add(slotOf(c.dot, TYPE_HUE[t]));
      }
      expect(slots.size, `${t} 命中色槽（${[...slots].sort().join(' ')}）`).toBe(12);
    }
  });

  // ── 7. 个体可辨（N10 的核心判据；#1418 的反例守护）─────────────────
  it('N10 同类型 8 实体：最大单通道差 ≥ 40（肉眼可辨，非「rgb 字符串不等」）', () => {
    let maxDot = 0;
    let maxBg = 0;
    for (let i = 0; i < EIGHT_CHARS.length; i += 1) {
      const a = deriveNodeColor(EIGHT_CHARS[i]);
      for (let j = i + 1; j < EIGHT_CHARS.length; j += 1) {
        const b = deriveNodeColor(EIGHT_CHARS[j]);
        maxDot = Math.max(maxDot, maxChannelDelta(a.dot, b.dot));
        maxBg = Math.max(maxBg, maxChannelDelta(a.bg, b.bg));
      }
    }
    // 判据与原型 shot 脚本一致：dot 差 ≥ 40 或 bg 差 ≥ 30
    expect(maxDot >= 40 || maxBg >= 30, `maxDot=${maxDot} maxBg=${maxBg}`).toBe(true);
  });

  it('#1418 反例守护：8 个同类型实体圆点色种数 > 4（旧 6 槽实测仅 4 色、碰撞组 3+3）', () => {
    const dots = new Set(EIGHT_CHARS.map((n) => deriveNodeColor(n).dot));
    expect(dots.size, `色种数 ${dots.size}（旧实现 = 4）`).toBeGreaterThan(4);
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

  // ── 8. 类型可辨（图例基准色）──────────────────────────────────
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
