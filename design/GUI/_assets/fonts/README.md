# 原型自托管字体（#1460）：serif 主栈 + sans 兜底层

`design/GUI/*/*.html` 的两个字体 token 原先是**本机字体栈**：

- `--font-serif:"Noto Serif SC","Source Han Serif SC","SimSun","宋体",Georgia,serif`
- `--font-ui:"PingFang SC","Microsoft YaHei","Noto Sans SC","Segoe UI",sans-serif`

字体栈是「机器相关」的：CI runner 上解析到的字体与出图机器不同 → 字形栅格化不同
→ 层② 原型 PNG↔HTML 同源性门禁（`ci_cd/check_gui_png_homology.py`）**假漂移**。
本目录把两族字体**随仓库分发**，让原型渲染与字体环境无关：门禁可以进 CI，
原型截图在任何机器/任何协作者上都是同一张图。

## 为什么必须自托管 sans 兜底层

serif 自托管后，CI 上 `gui-png-homology` 仍剩 **2/107 漂移**
（`world state=plan-b` / `world state=plan-c` 的评审注解行）。根因是
`--font-ui` 里的 **`"Noto Sans SC"` 是本机专有条目**——出图机器装了它，CI runner 没装。
Microsoft YaHei 缺的 3 个字形 `↔`(U+2194) `⇒`(U+21D2) `⚠`(U+26A0) 于是两端解析不同
（本机落到 13px Noto Sans SC / CI 落到 11px Segoe UI）→ 整行换行不同。

修法 = 把 sans 也子集化入库，并在 `--font-ui` 的 `"Microsoft YaHei"` 之后、
`"Noto Sans SC"` **之前**插入 `InkFlow Sans`。（`--font-serif` 的问题是 PR #1459
实测的 **91/107 漂移**，bbox 一律自 `(44, 16)` 起、maxdiff 129–215，由 serif 自托管解决。）

## 文件

| 文件 | 说明 |
|------|------|
| `inkflow-serif-400.woff2` | `--font-serif` 字重 400 子集 |
| `inkflow-serif-600.woff2` | `--font-serif` 字重 600 子集（品牌字 / 页标题 / 卡片标题 / 对话框标题） |
| `inkflow-sans-400.woff2` | `--font-ui` 兜底层字重 400 子集 |
| `inkflow-sans-600.woff2` | `--font-ui` 兜底层字重 600 子集 |
| `OFL.txt` | 字体许可原文 |
| `subset-manifest.json` | 子集清单（字符集指纹 + 每个文件的字节数 / SHA256 / 覆盖数 / 缺字集合） |
| `build-subset.py` | 子集构建脚本（可复现；需网络，一次生成 4 个 woff2 + 清单） |

**体积（两族合计 ≈ 673 KB）**：

| 族 | 400 | 600 |
|----|-----|-----|
| `InkFlow Serif` | 191,640 B | 194,764 B |
| `InkFlow Sans` | 149,996 B | 152,348 B |

未子集的完整字体为 14.8 MB / 单字重 / 族。

## 栈位置规则（**load-bearing，勿动**）

`ci_cd/tests/test_gui_selfhost_font.py` 逐项断言两个 token 的栈形：

```
--font-serif:"InkFlow Serif","Noto Serif SC","Source Han Serif SC","SimSun","宋体",Georgia,serif;
--font-ui:"PingFang SC","Microsoft YaHei","InkFlow Sans","Noto Sans SC","Segoe UI",sans-serif;
```

`InkFlow Sans` **必须留在 `"Microsoft YaHei"` 之后、`"Noto Sans SC"` 之前**：

- 放到 `"Microsoft YaHei"` **之前** → 全部正文换字体（不只兜底那 3 个符号），
  与上一轮定稿的渲染结果不一致；
- 放到 `"Noto Sans SC"` **之后** → 本机（装了 Noto Sans SC）仍优先命中它，
  自托管面**永远不会生效**，漂移照旧。

## 许可与来源

- **字体**：Noto Serif SC（Static，v2.003-H1） / Noto Sans SC（Static）
- **版权**：`(c) 2017-2024 Adobe (http://www.adobe.com/)`，`(c) 2012 Google Inc.`
- **许可**：SIL Open Font License 1.1（**OFL-1.1**，允许再分发/子集化；见 `OFL.txt`）
- **分发渠道**：Google Fonts（`fonts.googleapis.com` → 字体文件 `fonts.gstatic.com`）
- **取法**（脚本里实现）：Google Fonts CSS API 在普通 UA 下只返回按 `unicode-range`
  切片的 woff2（覆盖不到原型用到的箭头/圈号等符号）；改用 legacy UA 请求同一 API 会经
  `/l/font?kit=` 返回**完整字体**（EOT 容器，body 即完整 SFNT）→ 剥离容器头 → 子集化。

## 子集化方式

```powershell
uv run --no-project --with fonttools --with brotli python `
    design/GUI/_assets/fonts/build-subset.py
```

- **字符集**：`design/GUI/**/*.html` 里出现过的全部字符（含 JS 字符串与文案），
  当前 **1152 个**（其中 CJK 1011）。**两族共用同一份字符集**。
- **字重**：每族 `400` / `600`（`WEIGHTS = (400, 600)`）。
- **选项**：`--layout-features=* --name-IDs=* --name-legacy --notdef-glyph --notdef-outline`
  （保留 kern 等排版特性，贴近完整字体的排版结果）。
- **确定性**：`TTFont(..., recalcTimestamp=False)`——否则 `head.modified` 每次保存都写成
  「当前时间」，同一字符集连跑两次会得到不同 SHA256。连跑两次 SHA256 必须一致。
- **族名改写**：子集内改名为 `InkFlow Serif` / `InkFlow Sans`——与系统里可能安装的
  `Noto Serif SC` / `Noto Sans SC` 区分开，使「@font-face 加载失败」立刻表现为回退到
  别的字体，而不是「看起来一样」把故障藏起来。

## 维护

新增/修改原型文案若引入了**字体里没有的新字符**，`ci_cd/tests/test_gui_selfhost_font.py`
的覆盖率用例会失败。此时：

1. 重跑上面的 `build-subset.py`（字符集自动从原型 HTML 重新收集，一次更新 4 个 woff2 + 清单）；
2. 重出受影响的页面 PNG（`design/GUI/_tools/shot-*.cjs`）。

## 残留的机器相关性（已知边界）

完整 Noto Serif SC / Noto Sans SC 本身**都不含**以下 **9 个码位**，它们仍由系统字体兜底
（不在任一子集内，`subset-manifest.json` 的 `missing_codepoints` 逐族登记）：

- `U+000A`（换行）、`U+FE0F`（变体选择符）：非「可见字形」意义上的字符；
- `U+25B8` `U+25BE`（`▸` `▾` 详情/折叠三角）→ 落到 Windows 符号字体；
- `U+2705` `U+1F4CE` `U+1F534` `U+1F5FA` `U+1F9E0`（`✅` `📎` `🔴` `🗺` `🧠` 等 emoji）
  → 落到系统 emoji 字体。

该兜底集合对**两族完全相同**（契约测试逐族断言「字体不含的码位 == 文档化兜底集合」）。
层② 门禁在 CI 与本机均为 Windows 环境，上述兜底字体一致；**若换到非 Windows 渲染端，
这几处仍可能产生漂移**——届时按门禁的豁免表登记，不要静默放宽阈值。
