/**
 * S3c 契约一致性门禁（C1）：前端 api/*.ts ↔ 后端 OpenAPI 快照自动对拍。
 *
 * 契约方向铁律：**后端 OpenAPI schema 是唯一真相**，前端手写 DTO/调用面必须对齐后端；
 * 禁止改后端契约迁就前端。本测试守：
 *  - M1：仓库快照 ci_cd/openapi_snapshot.json 存在（配套后端
 *    backend/tests/unit/test_openapi_contract.py 断快照与 app.openapi() 一致）
 *  - M2：每个 api 模块调用面的 ①路径/方法 ②query 参数名 ③请求体字段名/类型
 *    与快照一致（前端多传后端未声明的 query = 静默失效，正是本门禁要抓的）
 *  - M4：openapi-typescript 生成类型 src/api/schema/openapi.d.ts 存在且与快照
 *    端点集合一致（前端可基于生成类型而非手写 DTO）
 *
 * TDD RED（2026-09-02）锚点：chat.ts fetchChatConversations 发 `project_id` query，
 * 后端 GET /api/v1/chat/conversations 只声明 include_deleted（ChatPanel.tsx:151
 * 注释自证「后端忽略 project_id」）→ 对拍必 FAIL，直至前端去掉无效 query。
 *
 * 解析器说明：不引入 AST 依赖，用平衡括号扫描自实现 TS 模板字符串解析
 * （`${projectId}`、`${qs ? `?${qs}` : ''}` 等嵌套模板是正则不可达的）。
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url)); // -> src/api/__contract__
const PKG_ROOT = join(HERE, '..', '..', '..'); // -> packages/renderer/
const REPO_ROOT = join(PKG_ROOT, '..', '..', '..'); // -> repo 根（frontend/packages/renderer 上三级）
const SNAPSHOT_PATH = join(REPO_ROOT, 'ci_cd', 'openapi_snapshot.json');
const API_DIR = join(HERE, '..'); // -> src/api
const GEN_TYPES_PATH = join(API_DIR, 'schema', 'openapi.d.ts');

interface OpenApiOperation {
  parameters?: { name: string; in: string; required?: boolean }[];
  requestBody?: { content?: { 'application/json'?: { schema?: JsonSchema } } };
  responses?: Record<string, { content?: { 'application/json'?: { schema?: JsonSchema } } }>;
}
interface JsonSchema {
  $ref?: string;
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  /** JSON Schema 枚举成员（OpenAPI 领域枚举）——类型解析时归一为 string */
  enum?: unknown[];
  /** 组合子：可选联合（如 T | null、$ref 枚举） */
  anyOf?: JsonSchema[];
  /** 字段默认值：后端有默认值时前端可选不算契约违规 */
  default?: unknown;
}
interface OpenApiSnapshot {
  paths: Record<string, Record<string, OpenApiOperation>>;
  components?: { schemas?: Record<string, JsonSchema> };
}

function loadSnapshot(): OpenApiSnapshot {
  return JSON.parse(readFileSync(SNAPSHOT_PATH, 'utf-8')) as OpenApiSnapshot;
}

/** 解析 $ref / 直取 schema 对象（快照内部 components/schemas 解引用一层即可） */
function resolveSchema(doc: OpenApiSnapshot, schema: JsonSchema | undefined): JsonSchema | undefined {
  if (!schema) return undefined;
  if (schema.$ref) {
    const name = schema.$ref.split('/').pop();
    return name ? doc.components?.schemas?.[name] : undefined;
  }
  return schema;
}

/** 取某 operation 的 query 参数名集合 */
function declaredQueryParams(op: OpenApiOperation | undefined): Set<string> {
  return new Set((op?.parameters ?? []).filter((p) => p.in === 'query').map((p) => p.name));
}

/** 取某 operation 的 200/201 JSON 响应 schema（解析 $ref） */
function responseSchema(doc: OpenApiSnapshot, op: OpenApiOperation | undefined): JsonSchema | undefined {
  for (const code of ['200', '201']) {
    const s = op?.responses?.[code]?.content?.['application/json']?.schema;
    const r = resolveSchema(doc, s);
    if (r) return r;
  }
  return undefined;
}

/** 取某 operation 的 requestBody JSON schema（解析 $ref） */
function requestSchema(doc: OpenApiSnapshot, op: OpenApiOperation | undefined): JsonSchema | undefined {
  return resolveSchema(doc, op?.requestBody?.content?.['application/json']?.schema);
}

// ---------------------------------------------------------------------------
// TS 源码轻量解析（平衡括号扫描，非正则）
// ---------------------------------------------------------------------------

/** 按 `export async function ` 切分：返回 函数名 -> 函数体文本（到大括号配平） */
function parseAsyncFunctions(src: string): Map<string, string> {
  const out = new Map<string, string>();
  const marker = 'export async function ';
  let idx = 0;
  while ((idx = src.indexOf(marker, idx)) !== -1) {
    const nameMatch = /^\w+/.exec(src.slice(idx + marker.length));
    // 函数体起始 { = 参数列表括号配平后、泛型（Promise<{...}>）之外的第一个 {
    let pd = 0; // paren depth
    let gd = 0; // generic angle-bracket depth
    let braceStart = -1;
    for (let i = idx + marker.length; i < src.length; i++) {
      const ch = src[i];
      if (ch === '(') pd++;
      else if (ch === ')') pd--;
      else if (ch === '{' && pd === 0 && gd === 0) {
        braceStart = i;
        break;
      } else if (pd === 0 && ch === '<') gd++;
      else if (pd === 0 && ch === '>') gd = Math.max(0, gd - 1);
    }
    if (nameMatch && braceStart !== -1) {
      const end = matchBalanced(src, braceStart, '{', '}');
      out.set(nameMatch[0], src.slice(braceStart + 1, end));
    }
    idx = braceStart !== -1 ? braceStart : idx + marker.length;
  }
  return out;
}

/** 从 pos 处的 open 括号扫描到配平的 close 括号，返回 close 的下标 */
function matchBalanced(src: string, pos: number, open: string, close: string): number {
  let depth = 0;
  for (let i = pos; i < src.length; i++) {
    if (src[i] === open) depth++;
    else if (src[i] === close) {
      depth--;
      if (depth === 0) return i;
    }
  }
  return src.length;
}

/** 函数体内所有含 /api/v1 的反引号模板串（不依赖调用点正则，覆盖变量中转场景） */
function extractCallTargets(body: string): string[] {
  const out: string[] = [];
  let i = 0;
  while ((i = body.indexOf('`', i)) !== -1) {
    const end = findTemplateEnd(body, i);
    if (end === -1) break;
    const content = body.slice(i + 1, end);
    if (content.includes('/api/v1')) out.push(content);
    i = end + 1;
  }
  return out;
}

/** 找反引号模板串的结束反引号（跳过 ${...} 内部，含嵌套模板） */
function findTemplateEnd(src: string, backtickPos: number): number {
  let i = backtickPos + 1;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '\\') {
      i += 2;
      continue;
    }
    if (ch === '`') return i;
    if (ch === '$' && src[i + 1] === '{') {
      i = matchBalanced(src, i + 1, '{', '}') + 1;
      continue;
    }
    i++;
  }
  return -1;
}

/** 模板串静态化：${...} -> {}，返回 { path, hasDynamicQuery } */
function normalizeTemplatePath(tpl: string): { path: string; hasDynamicQuery: boolean } {
  let out = '';
  let i = 0;
  let hasDynamicQuery = false;
  while (i < tpl.length) {
    if (tpl.startsWith('${baseURL}', i)) {
      i += '${baseURL}'.length;
      continue;
    }
    if (tpl[i] === '$' && tpl[i + 1] === '{') {
      const end = matchBalanced(tpl, i + 1, '{', '}');
      const inner = tpl.slice(i + 2, end);
      // 整体作为 query 后缀的模板（如 ${suffix} / ${qs ? `?${qs}` : ''}）
      if (/^(suffix|qs\b|query\b)/.test(inner.trim())) hasDynamicQuery = true;
      else out += '{}';
      i = end + 1;
      continue;
    }
    out += tpl[i];
    i++;
  }
  return { path: out, hasDynamicQuery };
}

/** 函数体内出现的 query key 全集：qs.set('k' / URLSearchParams 对象字面量键 / 内联 ?k= / &k= */
function collectQueryKeys(body: string): Set<string> {
  const keys = new Set<string>();
  for (const m of body.matchAll(/(?:qs|query|params|searchParams|sp)\.set\(\s*['"]([^'"]+)['"]/g)) keys.add(m[1]);
  for (const m of body.matchAll(/new URLSearchParams\(\{([\s\S]*?)\}\)/g)) {
    for (const k of m[1].matchAll(/(\w+)\s*:/g)) keys.add(k[1]);
  }
  for (const m of body.matchAll(/[?&]([a-zA-Z_]\w*)=/g)) keys.add(m[1]);
  return keys;
}

/** 提取 `export interface X { ... }` 字段：name -> { type 文本, optional } */
function parseInterface(src: string, name: string): Map<string, { type: string; optional: boolean }> | undefined {
  const re = new RegExp(`export interface ${name}\\s*\\{`);
  const m = re.exec(src);
  if (!m) return undefined;
  const start = src.indexOf('{', m.index);
  const end = matchBalanced(src, start, '{', '}');
  const body = src.slice(start + 1, end);
  const out = new Map<string, { type: string; optional: boolean }>();
  for (const line of body.split('\n')) {
    const fm = /^\s*(\w+)(\?)?\s*:\s*(.+?)\s*;?\s*$/.exec(line);
    if (fm && !/^\s*(\/\/|\*|\/\*)/.test(line)) out.set(fm[1], { type: fm[3].replace(/;$/, '').trim(), optional: !!fm[2] });
  }
  return out;
}

/** TS 标量类型 -> 归一集合（如 `string | null` -> {string} + nullable） */
function tsScalarTypes(typeText: string): Set<string> {
  const t = typeText.replace(/\s+/g, '');
  const types = new Set<string>();
  for (const part of t.split('|')) {
    if (/^'/.test(part) || /^"/.test(part)) types.add('string');
    else if (part === 'string' || part === 'number' || part === 'boolean') types.add(part);
    else if (/^Record</.test(part)) types.add('object');
    else if (/^\w+\[\]$/.test(part)) types.add('array');
    else types.add('other'); // 具名 interface 引用等，不参与标量比对
  }
  return types;
}

/** OpenAPI schema -> 归一类型集合（anyOf/enum/$ref 展开） */
function jsonScalarTypes(doc: OpenApiSnapshot, s: JsonSchema | undefined): Set<string> {
  if (!s) return new Set(['other']);
  const resolved = resolveSchema(doc, s);
  if (!resolved) return new Set(['other']);
  const out = new Set<string>();
  if (resolved.type) out.add(resolved.type);
  if (resolved.enum) out.add('string');
  if (resolved.anyOf) {
    for (const sub of resolved.anyOf) {
      const st = sub.$ref ? 'string' : sub.type ?? (sub.enum ? 'string' : undefined); // 领域枚举 $ref 归 string
      if (st) out.add(st === 'integer' ? 'integer' : st);
      else if (sub.type !== 'null') for (const t of jsonScalarTypes(doc, sub)) out.add(t);
    }
  }
  if (out.size === 0) out.add('other');
  return out;
}

/** 模板路径 -> 匹配快照 path template（{} 段与 :param 段互配） */
function matchSnapshotPath(doc: OpenApiSnapshot, method: string, path: string): string | undefined {
  const segs = path.split('/');
  const methodKey = method.toLowerCase();
  for (const p of Object.keys(doc.paths)) {
    if (!(methodKey in (doc.paths[p] ?? {}))) continue;
    const ps = p.split('/');
    if (ps.length !== segs.length) continue;
    let ok = true;
    for (let i = 0; i < segs.length; i++) {
      const a = segs[i];
      const b = ps[i];
      if (b.startsWith('{') || a === '{}') continue;
      if (a !== b) {
        ok = false;
        break;
      }
    }
    if (ok) return p;
  }
  return undefined;
}

/** 函数体内显式 method:；apiFetch 无 method 默认 GET；fetch(url) 无 init 也是 GET */
function detectMethod(body: string): string {
  const m = /method:\s*['"](\w+)['"]/.exec(body);
  return m ? m[1].toUpperCase() : 'GET';
}

// ---------------------------------------------------------------------------
// 测试
// ---------------------------------------------------------------------------

describe('S3c 契约对拍：前端 api/*.ts ↔ 后端 OpenAPI 快照（后端为准）', () => {
  it('M1：仓库存在版本化 OpenAPI 快照（ci_cd/openapi_snapshot.json）', () => {
    expect(existsSync(SNAPSHOT_PATH), `快照缺失：${SNAPSHOT_PATH}。由 CI/脚本从 app.openapi() 导出`).toBe(true);
  });

  it('M4：openapi-typescript 生成类型存在且覆盖快照全部 path 端点', () => {
    const doc = loadSnapshot();
    expect(existsSync(GEN_TYPES_PATH), `生成类型缺失：${GEN_TYPES_PATH}（pnpm gen:api）`).toBe(true);
    const gen = readFileSync(GEN_TYPES_PATH, 'utf-8');
    // 快照全部 path 必须出现在生成类型的 paths 键区
    // （openapi-typescript 输出以双引号键名声明 path，如 `"/api/v1/chat/conversations":`）
    for (const p of Object.keys(doc.paths)) {
      expect(gen, `生成类型缺少端点 ${p}（重跑 pnpm gen:api 刷新快照对应类型）`).toContain(`"${p}"`);
    }
  });

  describe('M2：调用面（路径/方法/query 参数）逐模块对拍', () => {
    // 全模块覆盖（M2「每个 api 模块」）：client.ts 是 apiFetch 封装本身、index.ts 是纯 re-export，排除
    const MODULES = readdirSync(API_DIR)
      .filter((f) => f.endsWith('.ts') && !f.endsWith('.test.ts') && !['client.ts', 'index.ts'].includes(f))
      .sort();

    for (const file of MODULES) {
      it(`${file}：每个导出 apiFetch 调用的路径/方法存在于快照，且 query key 均被后端声明`, () => {
        const doc = loadSnapshot();
        const src = readFileSync(join(API_DIR, file), 'utf-8');
        const fns = parseAsyncFunctions(src);
        expect(fns.size, `${file} 未解析到任何导出函数`).toBeGreaterThan(0);
        const violations: string[] = [];
        for (const [fnName, body] of fns) {
          if (!/apiFetch|fetch\(/.test(body)) continue;
          const method = detectMethod(body);
          for (const tpl of extractCallTargets(body)) {
            const { path: rawPath, hasDynamicQuery } = normalizeTemplatePath(tpl);
            if (!rawPath.startsWith('/api/v1')) continue; // 非 API 目标（如 baseURL 变量拼参）
            const qIdx = rawPath.indexOf('?');
            const staticPath = qIdx === -1 ? rawPath : rawPath.slice(0, qIdx);
            const matched = matchSnapshotPath(doc, method, staticPath);
            if (!matched) {
              violations.push(`${fnName}: ${method} ${staticPath} 不在快照`);
              continue;
            }
            const op = doc.paths[matched]?.[method.toLowerCase() as string];
            const declared = declaredQueryParams(op);
            const used = collectQueryKeys(body);
            if (hasDynamicQuery) {
              // 动态 query 由 URLSearchParams 构造：keys 已入 used（qs.set / 对象字面量）
            }
            const extra = [...used].filter((k) => !declared.has(k));
            if (extra.length > 0) {
              violations.push(
                `${fnName}: ${method} ${matched} 前端多传后端未声明的 query ${JSON.stringify(extra.sort())}（后端声明：${JSON.stringify([...declared].sort())}）`,
              );
            }
          }
        }
        expect(violations, `契约不匹配（前端 → 后端方向）：\n${violations.join('\n')}`).toEqual([]);
      });
    }

    it('chat.ts#fetchChatConversations：后端 GET /chat/conversations 声明面（RED 锚点显式锁定）', () => {
      const doc = loadSnapshot();
      const op = doc.paths['/api/v1/chat/conversations']?.get;
      expect(op, '快照缺 GET /api/v1/chat/conversations').toBeTruthy();
      const declared = declaredQueryParams(op);
      // 后端真相：仅 include_deleted。前端如要 project 过滤需走后端能力，
      // 不允许发后端未声明的 project_id（被忽略 = 静默跨项目数据）。
      expect([...declared]).toEqual(['include_deleted']);
      const src = readFileSync(join(API_DIR, 'chat.ts'), 'utf-8');
      const body = parseAsyncFunctions(src).get('fetchChatConversations');
      expect(body, 'chat.ts 未找到 fetchChatConversations').toBeTruthy();
      const used = collectQueryKeys(body ?? '');
      expect(used.has('project_id'), 'fetchChatConversations 不得发 project_id（后端未声明，query 被静默忽略）').toBe(false);
    });
  });

  describe('M2：DTO 字段名/类型对拍（请求体 + typed 响应）', () => {
    interface DtoContract {
      file: string;
      iface: string;
      op: [method: string, path: string];
      side: 'request' | 'response';
      /** 响应数组字段：schema = properties[itemOf].items（$ref 解引用后），前端 iface 对齐 item 结构 */
      itemOf?: string;
    }

    const CONTRACTS: DtoContract[] = [
      {
        file: 'knowledge-graph.ts',
        iface: 'KnowledgeRelationCreateInput',
        op: ['POST', '/api/v1/projects/{project_id}/knowledge-relations'],
        side: 'request',
      },
      { file: 'search.ts', iface: 'SearchResponseDto', op: ['GET', '/api/v1/search'], side: 'response' },
      { file: 'search.ts', iface: 'SearchHitDto', op: ['GET', '/api/v1/search'], side: 'response', itemOf: 'hits' },
    ];

    for (const c of CONTRACTS) {
      it(`${c.iface} 字段名/标量类型 ↔ ${c.op[0]} ${c.op[1]}（${c.side}${c.itemOf ? `.items[${c.itemOf}]` : ''}）`, () => {
        const doc = loadSnapshot();
        const src = readFileSync(join(API_DIR, c.file), 'utf-8');
        const fields = parseInterface(src, c.iface);
        expect(fields, `${c.file} 未找到 interface ${c.iface}`).toBeTruthy();

        const methodKey = c.op[0].toLowerCase();
        const snapOp = doc.paths[c.op[1]]?.[methodKey];
        expect(snapOp, `快照缺 ${c.op[0]} ${c.op[1]}`).toBeTruthy();
        let schema: JsonSchema | undefined;
        if (c.side === 'request') schema = requestSchema(doc, snapOp);
        else schema = responseSchema(doc, snapOp);
        if (c.itemOf && schema?.properties?.[c.itemOf]?.items) {
          schema = resolveSchema(doc, schema.properties[c.itemOf].items);
        }
        expect(schema?.properties, `${c.op[1]} ${c.side} 无 properties（后端未建模，跳过字段对拍）`)?.toBeDefined();
        const props = schema!.properties!;
        const required = new Set(schema!.required ?? []);

        const mismatches: string[] = [];
        for (const [name, f] of fields!) {
          if (!(name in props)) {
            mismatches.push(`前端字段 ${name} 在后端 ${c.side} schema 中不存在（改名/删除风险）`);
            continue;
          }
          const tsTypes = tsScalarTypes(f.type);
          const jsTypes = jsonScalarTypes(doc, props[name]);
          const comparable = [...tsTypes].filter((t) => t !== 'other');
          if (comparable.length === 0) continue; // 具名类型引用不参与标量比对
          for (const t of comparable) {
            if (!jsTypes.has(t) && !(t === 'number' && jsTypes.has('integer'))) {
              mismatches.push(`${name}: TS 类型 ${f.type} 与后端 ${JSON.stringify([...jsTypes])} 不兼容`);
            }
          }
          // 必填性：前端可选但后端必填 = 运行期 422/undefined 风险
          if (f.optional && required.has(name) && !(props[name].default !== undefined)) {
            mismatches.push(`${name}: 后端 required 但前端可选（无默认值兜底）`);
          }
        }
        expect(mismatches, `DTO 对拍失败：\n${mismatches.join('\n')}`).toEqual([]);
      });
    }
  });
});
