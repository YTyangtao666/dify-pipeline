# dify-pipeline v2 优化方案：从「生图流水线」到「AI 电商视觉系统」

> 依据《AI电商做图工作流十一层》方法论设计。
> 核心认知：**让 AI 先当运营，再当美工**——前 8 层定方向，第 9 层出图，第 10/11 层数据回流训练。
> 原则：图不是做出来就完，要抢点击、讲卖点、打消顾虑、看转化。

---

## 一、现状对照（Gap 分析）

| 层 | 方法论要求 | 现状 | 差距 |
|---|---|---|---|
| L1 产品分析 | 人群画像/使用场景/核心卖点清单 | products.json 只有标题+描述 | ❌ 缺整层 |
| L2 竞品分析 | 价格带/主打卖点/差异化切口 | 无 | ❌ 缺整层 |
| L3 爆款图库 | 分平台分类目分风格沉淀 | 无（仅脚本库+方法论 md） | ❌ 缺整层 |
| L4 爆款拆解 | VLM 拆视觉/文案/心理/平台特征 | 无 | ❌ 缺整层 |
| L5 框架库 | 卖点/版式/钩子/结构框架，可复用可迭代 | **8 屏结构已实现**（storyboard.py） | 🟡 部分有，未结构化成库 |
| L6 用户反馈 | 好评差评问答 → 痛点词云/高频问题/信任缺口 | 无 | ❌ 缺整层 |
| L7 卖点排序 | 卖点优先级表（Top3 打穿） | 无（生图 prompt 平铺所有卖点） | ❌ 缺整层 |
| L8 设计方向 | 风格/色彩/构图/提示词 brief | 无（风格硬编码 STYLES） | ❌ 缺整层 |
| L9 一键出图 | 按商业判断执行 | **已实现**（02 生图 + 8屏模式） | ✅ 最强一环 |
| L10 数据测试 | CTR/CVR/收藏加购回流 | 无 | ❌ 缺整层 |
| L11 反馈迭代 | 归因 → 更新框架库 | **雏形已有**（<80% → LLM 建议） | 🟡 单次建议，不回流沉淀 |

**结论**：v1 是「第 9 层很强，前后十层空转」。v2 补齐前八层分析链 + 第 10/11 层闭环。

---

## 二、目标架构

```
┌─────────────────── 分析链（出图前，LLM 驱动）───────────────────┐
│                                                                  │
│  L1 产品分析 ──→ L6 用户反馈 ──→ L7 卖点排序 ──→ L8 设计方向      │
│  (产品主档)      (评论采集)      (优先级表)     (design_brief)    │
│       ↑                                              │           │
│  L2 竞品分析 (京东同类目爬取+对比)                      │           │
│       ↑                                              ↓           │
│  L3 爆款图库 (飞书多维表格) ──→ L4 爆款拆解(VLM) ──→ L5 框架库    │
│                                            (frameworks.json)     │
└──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────── 执行链（已有，升级）──────────────────────────┐
│  L9 一键出图：02 生图 ← design_brief 驱动（替代硬编码 STYLES）     │
│  03 VLM 质检：评分标准从「好不好看」升级为「打不打得穿 Top3 卖点」   │
└──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────── 反馈链（新增）───────────────────────────────┐
│  L10 数据测试：投放数据导入（CTR/CVR/加购）→ test_results.json    │
│  L11 归因迭代：LLM 归因（卖点/人群/风格/信任）→ 更新框架库评分      │
│       ↑______________回流到 L5 框架库 + L8 设计方向______________↑ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、数据资产设计（全部 JSON，git 可版本化）

```
data/
├── products.json                 # 输入：商品主档（扩展 category/价格带/目标人群）
├── product_profile_{pid}.json    # L1产出：人群画像/使用场景/核心卖点清单
├── competitors_{pid}.json        # L2产出：竞品对比（价格带/卖点/差异化切口）
├── hot_library/                  # L3：爆款图库（飞书多维表格为 UI，导出 JSON 同步）
│   ├── library.json              #   条目：图/平台/类目/风格/标签/来源
│   └── teardown_{id}.json        # L4产出：单图拆解（视觉/文案/心理/平台四维）
├── frameworks.json               # L5：框架库（8屏结构迁入+主图框架+钩子库）
│                                 #   每框架带 score 字段（L11 迭代更新）
├── feedback_{pid}.json           # L6产出：痛点词云/高频问题/信任缺口
├── selling_points_{pid}.json     # L7产出：卖点优先级表（Top3 必打穿）
├── design_brief_{pid}.json       # L8产出：风格/色彩/构图/提示词方向
└── test_results_{pid}.json       # L10导入：图×CTR×CVR×加购
```

**框架库结构**（L5，核心资产，L11 的回流目标）：
```json
{
  "frameworks": [
    {
      "id": "fw_8screen_v1",
      "type": "详情页",
      "name": "8屏视觉逼单",
      "structure": [...8屏...],
      "applies_to": {"品类": "常规消费品", "客单": "6-10屏场景"},
      "score": {"wins": 12, "losses": 3, "win_rate": 0.8, "updated": "..."},
      "source": "飞书方法论文档"
    }
  ]
}
```

---

## 四、模块与 TDD 计划（延续 RED→GREEN）

### P0：文本分析链（只依赖 DeepSeek 官方 key，立即可跑）

| 模块 | 职责 | 关键测试点 |
|---|---|---|
| `analyzer/product.py` (L1) | 商品主档 → LLM 产出画像/场景/卖点清单 | prompt 组装、JSON 提取（复用 evaluator.extract_json）、缺字段兜底 |
| `analyzer/competitor.py` (L2) | 京东同类目爬取(复用01) + LLM 对比定位 | 竞品去重、差异化结论结构化、价格带统计 |
| `analyzer/feedback.py` (L6) | 评论采集（京东评论接口）+ LLM 提炼 | 词云频次、信任缺口分类、差评聚类 |
| `analyzer/selling_points.py` (L7) | 卖点×痛点×竞品差异 LLM 映射排序 | **Top3 唯一性断言**、优先级分值单调 |
| `analyzer/brief.py` (L8) | 全量输入 → design_brief + 生图提示词 | brief 完整性（风格/色彩/构图/负面）、与 Top3 卖点一致性 |
| `analyzer/llm.py` | DeepSeek 官方客户端（重试/JSON提取复用） | 429 退避、reasoning 模型 content-null 兜底 |

### P1：视觉链（依赖 VLM，yunwu 配额恢复后）

| 模块 | 职责 | 关键测试点 |
|---|---|---|
| `analyzer/teardown.py` (L4) | VLM 拆爆款图四维（视觉/文案/心理/平台） | 四维字段齐、无「好看」类空洞结论（断言具体词） |
| `03 evaluator 升级` | 质检标准升级：是否打穿 Top3 卖点（读取 selling_points） | 评分维度变更、旧报告兼容 |

### P2：反馈闭环

| 模块 | 职责 | 关键测试点 |
|---|---|---|
| `feedback/importer.py` (L10) | 导入投放数据 CSV/JSON → test_results | 字段校验、图片映射 |
| `feedback/iterator.py` (L11) | LLM 归因（卖点/人群/风格/信任四假设）→ 更新 frameworks.score | 归因结论结构化、score 单调更新、框架淘汰逻辑 |

---

## 五、CLI 与 Dify 编排演进

### CLI 新增
```
05_analyze.py --product P001              # 一键跑 L1→L2→L6→L7→L8，产出 design_brief
06_teardown.py --image xxx.png --library  # L4 拆图入库
07_import_results.py --csv results.csv    # L10 导入投放数据
08_iterate.py --product P001              # L11 归因+更新框架库
```

### Dify 演进：单工作流 → 双工作流
1. **「分析工作流」**（新增）：开始(product_id) → HTTP /analyze → LLM节点(审阅 design_brief，可人工改) → 结束
   - 分析是 LLM 密集型，Dify 的 LLM 节点做「设计总监审阅」人机协同点
2. **「生产工作流」**（现有，升级）：生图节点改读 design_brief（`/generate?brief=1`）；评分分支保持
3. **「迭代工作流」**（新增）：开始(导入数据) → HTTP /import → LLM 归因节点 → HTTP /update-frameworks → 结束

launchd 定时从「每日出图」升级为「每日出图 + 每周迭代」。

---

## 六、实施顺序与依赖

| 阶段 | 内容 | 依赖 | 预计 |
|---|---|---|---|
| P0-a | analyzer/llm.py + product.py (L1) | DeepSeek key ✅ | TDD 半天 |
| P0-b | feedback.py 评论采集 (L6) + selling_points (L7) + brief (L8) | 同上 | 1 天 |
| P0-c | 05_analyze.py 串链 + api_server /analyze + Dify 分析工作流 | 同上 | 半天 |
| P1 | teardown (L4) + 03 升级 | **yunwu 配额** | 1 天 |
| P2 | 反馈导入 + 归因迭代 + 框架库 score | DeepSeek + 真实/模拟投放数据 | 1 天 |

**L3 爆款图库**：不写代码，直接建飞书多维表格（字段：图/平台/类目/风格/标签/四维拆解），复用已验证的 clientvars 导出管道同步为 JSON。

---

## 七、与现有资产的复用关系

- `evaluator.extract_json` / 重试框架 → analyzer/llm.py 直接复用
- `storyboard.EIGHT_SCREENS` → 迁入 frameworks.json 成为第一个框架（fw_8screen_v1）
- `scraper.scrape_jd` → L2 竞品爬取复用
- `video_scripts_100.json` → L6 的「问答」维度种子（视频脚本的痛点即买家关心点）
- `detail_page_method.md` → L5 框架库的方法论文档层

---

## 八、面试叙事升级（一句话）

> v1：「Dify 编排生图+质检+视频全链路」
> v2：「按十一层方法论构建的 AI 电商视觉**系统**：前八层让 AI 先当运营（产品/竞品/图库/拆解/反馈/卖点排序/设计方向），第九层才出图，第十/十一层用投放数据归因迭代框架库——做的不是一张图，是一套越用越准的视觉系统。」

---

## 九、原则红线（实施时遵守）

1. 所有 LLM 产出必须结构化 JSON 落盘（可追溯、可 diff）
2. 框架库 score 只能由 L11 迭代修改（单向数据流，防污染）
3. Top3 卖点唯一——生成 brief 时断言，超过 3 个视为 LLM 越权，重试
4. 每层独立可跑（单层失败不阻塞后续，降级用默认值并打标）
5. 沿用 TDD：每模块测试先行，全绿才 commit
