# 识图模型测评（Benchmark Design）— 谁识图最强

## 目标

测试 claude-opus-4-6 / gemini-3-flash-preview(=3.5-flash 系) / gpt-5.2-codex
三模型识图能力，为 dify-pipeline 选定质检（QC）评审模型。

## 基准哲学（先于一切）

**真值不来自任何参赛模型**（Same-Model Bias 红线 + 循环论证）：

1. **程序可测真值**（客观题）：像素统计 / 已知生成参数 / 已知标签——机器判分，零主观
2. **人工金标**（主观题）：用户肉眼裁决——每题给三模型盲答并排对比页

不设「模型裁判」。识图对比页用 HTML 生成（用户偏好可视化），人工点选最优。

## 参赛模型与通道（2026-08-17 实测）

| 模型 | 通道 | 状态 |
|---|---|---|
| claude-opus-4-6 | POST /v1/messages (Anthropic 原生, x-api-key) | ✓ 22s 首答 |
| gemini-3-flash-preview | POST /v1/chat/completions (OpenAI 兼容, stream:false) | ✓（"gemini-3.5-flash" 名不存在，用 3-flash-preview） |
| gpt-5.2-codex | POST /v1/responses | ✗ 网关持续忙 >4min（同族 gpt-5.3-codex / gpt-5.2 可用） |

gpt-5.2-codex 若开赛仍忙 → 替补 gpt-5.3-codex（同 Codex 系），开赛前再实测一次。

## 题库设计（5 维度 × 3 难度）

题源全部来自 dify-pipeline 真实产物（不造假数据）：

### D1 细粒度 OCR（印花文字逐字母）
- E: 00A 白底特写 → "SMOKE I DON'T"（含撇号/做旧残缺）
- M: 01 户外街拍（印花受褶皱/光影干扰）
- H: 06 局部特写（文字部分出画）

### D2 颜色保真（色相/饱和度命名）
- E: 00A 底色（淡黄）+ 印花色（粉红做旧）
- M: 07 夜景（灯光偏色下报 T 恤底色）
- H: 02/05 两图印花色差判断（轻微色差 vs 一致）

### D3 跨图人物一致性（本次痛点）
- E: 00B 三视图内部三人像是否同一人
- M: 01 vs 06（同景别异场景）
- H: 5 张模特图全员一致性 + 指认 outlier

### D4 商品一致性（跨图物体再认）
- E: 01 vs 03 T 恤是否同款
- M: 全 7 张印花文字一致性清点
- H: 00B 三视图三个视图服装是否完全一致 + 找茬（多/少元素）

### D5 抗幻觉（负向题——最防刷分）
- E: 「图中有几只猫？」（无猫，答 0 才得分）
- H: 「列出 T 恤上所有图案」（只应报印花文字，编造徽标/动物=幻觉扣分）

评分：E=1 / M=2 / H=3 分，满分 33 分（11 题×3）。附延迟与费用记录。

## 执行

1. 脚本 scripts/bench/vlm_bench.py：三模型逐题跑（重试 3×，超时 120s）
2. 输出 data/bench_results.json + 对比 HTML（暖白+香槟金，每题三答并排+金标标注）
3. 客观题自动判分（关键词精确匹配 + 颜色词归一化）；主观题留人工裁决区
4. 交付：报告 HTML 放桌面

## 已知坑（来自 apimart skill）

- chat 必须 stream:false；gemini max_tokens≥2000 防截断
- 经 7897 代理偶发 SSL EOF → 重试 2-3 次
- claude 用 Anthropic 原生消息格式；codex 用 Responses 格式
