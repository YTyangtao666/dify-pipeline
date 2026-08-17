# 电商素材批量生产 · 工作流方案设计 v2

> 现状问题：单预设零散生成 ≠ 真实电商需求。商家要的是「一套能直接上架的完整素材包」。
> 本方案：套餐化（Bundle）+ 批量引擎 + 按位命名 + 打包交付。

---

## 一、问题诊断（为什么现在的设计不合理）

| 现状 | 真实需求 |
|---|---|
| 8 个预设单选，一张张点 | 一个商品要 20-50 张图，覆盖 主图轮播/详情页/SKU/投放 |
| 生成完散落在 images/ | 需要按「用途+位置」命名（主图第2张=卖点图），能直接传后台 |
| 每张手动跑，失败重跑整套 | 需要：任务队列 + 并发 + 单张失败单独重跑 |
| 无成本概念 | 一套 30 张 ≈ apimart credits，跑之前要知道多少钱 |
| 质检是全量混评 | 应该按「素材包」为单位出报告：哪张不合格、为什么、要不要重跑 |

## 二、真实电商素材需求（设计输入）

以淘宝/天猫 + 小红书 + 投放 为参照，一个商品完整素材结构：

```
商品素材包 (Product Asset Bundle)
├── 主图轮播 5 张（1:1）     ← 平台硬性：第1张白底，2-5 卖点递进
├── 详情页 8 屏（750 宽竖图） ← 已有八屏方法论（detail_page_method.md）
├── SKU 矩阵 N 张            ← 每个规格/颜色一张
├── 场景种草 3-6 张（3:4）    ← 小红书/抖音
├── 模特图 2-4 张（3:4）      ← 服饰/日用品必备
└── 投放变体 6-12 张（1:1）   ← A/B 测试（同构图不同文案钩子）
```

## 三、套餐架构（Bundle = 编排逻辑 + 生成清单）

不是「预设的集合」，而是**带位置语义的清单**——每个位置定义：放什么、什么构图、什么比例、质检标准。

```python
BUNDLES = {
  "tmall_main5": {           # 天猫主图5张轮播
    "name": "天猫主图轮播包（5张）",
    "slots": [
      {"pos": 1, "role": "白底规范图",  "preset": "main_white",   "size": "1:1"},
      {"pos": 2, "role": "核心卖点图",  "preset": "selling_point","size": "1:1", "inject_top3": 0},
      {"pos": 3, "role": "场景使用图",  "preset": "scene_lifestyle","size": "1:1"},
      {"pos": 4, "role": "细节/工艺图", "preset": "detail_closeup","size": "1:1"},
      {"pos": 5, "role": "信任背书图",  "preset": "trust_badge",  "size": "1:1"},
    ]},
  "detail_8screen": {...},   # 详情页八屏（复用已有 storyboard）
  "xhs_pack6": {...},        # 小红书 6 张（3:4）
  "ab_test6": {...},         # 投放 A/B：1 个构图 × 6 文案钩子变体
  "full_launch": {...},      # 全量上架包 = main5 + detail8 + xhs6（19张）
}
```

关键设计：
- **slot 有 role**：生成的文件名 = `{pid}_main{pos}_{role}.png`，直接对应平台上架位置
- **inject_top3**：slot 级卖点注入开关（主图第2张必打 Top3[0]）
- **AB 变体**：同一 slot 生成 N 版（不同钩子文案），供投放赛马
- **依赖声明**：slot 声明 needs white/model，缺素材的 slot 自动跳过并报告，不阻塞整包

## 四、批量引擎（Batch Runner）

```
POST /generate/bundle {"product_id":"P001","bundle":"full_launch","variants":2}
```

1. **预检**：素材齐不齐（缺模特图→相关 slot 跳过）、预估成本（credits = 张数×单价）、预估时长
2. **队列**：slot 逐个入队，并发 2（gpt-image-2 异步任务本身可并行，提交后轮询不占线程）
3. **断点续跑**：manifest 记录每个 slot 状态；失败的 slot 单独重跑 `POST /generate/bundle?retry_failed=true`
4. **命名落盘**：`output/bundles/{pid}_{bundle}/{位置命名}.png`
5. **打包**：整包完成 → 自动 zip + 清单 CSV（文件名/角色/质检分/建议用途）

## 五、质检升级：按 Bundle 出报告

- 每张图仍走 VLM 评分（gemini-3.5-flash）
- 报告按 slot 聚合：`主图3/5 达标，pos4 细节图 65 分（文字模糊），建议重跑`
- AB 变体组：同一位置多版本对比分差，分差大的 slot 标记「构图不稳定」
- Top3 打穿率按 bundle 维度统计（这是投放效果的先行指标）

## 六、实现计划（TDD，5 个任务）

| 任务 | 内容 | 测试 |
|---|---|---|
| B1 | bundles.py 套餐定义 + slots 校验（素材缺失跳过逻辑） | ~8 tests |
| B2 | 批量引擎 runner（队列/并发2/manifest断点/单slot重跑） | ~8 tests |
| B3 | API：/bundles 列表、/generate/bundle、/bundle/{pid}/{name}/status | ~6 tests |
| B4 | studio.html v2：套餐卡片（含张数/成本预估）→ 一键整包 → 按位展示+失败重跑按钮 | E2E |
| B5 | 打包导出 zip + 清单 CSV + 按包质检报告 | ~5 tests |

真实 E2E：上传白底图 → tmall_main5（5张）→ 验证命名/质检/打包全链。

## 七、成本预估（apimart gpt-image-2，1k 档）

| 套餐 | 张数 | credits（实测~0.085/张） | 时长（并发2） |
|---|---|---|---|
| tmall_main5 | 5 | ~0.43 | ~3 分钟 |
| xhs_pack6 | 6 | ~0.51 | ~3 分钟 |
| detail_8screen | 8 | ~0.68 | ~4 分钟 |
| full_launch | 19 | ~1.6 | ~10 分钟 |

---

*方案日期 2026-08-17 · 对应仓库 state: 230e089 · 确认后按 B1-B5 顺序 TDD 实现*
