# AI 电商素材工厂 · 工作流具体设计文档

> 版本：v2.3（对应 commit ec62b3d）· 2026-08-17
> 定位：面向跨境电商（SHEIN 类）的服装/标品素材批量生产系统
> 状态：174 tests 全绿 · 真实 E2E 已跑通（T恤 8 图 376s / 连衣裙 8 图 420s / 保温杯 5 图 305s）

---

## 一、系统总览

```
                        ┌─────────────────────────────────────────┐
                        │            用户入口（三层）                │
                        │  studio.html 可视化 / Dify 画布 / cron 定时 │
                        └──────────────┬──────────────────────────┘
                                       ▼
                        ┌─────────────────────────────────────────┐
                        │         FastAPI 服务 (127.0.0.1:8100)     │
                        │  /assets/*上传  /generate/compose 单图     │
                        │  /bundles 列表  /generate/bundle 整包      │
                        │  /evaluate 质检 /report 报告               │
                        └──────────────┬──────────────────────────┘
                                       ▼
     ┌─────────────────┬───────────────┴──────────────┬─────────────────────┐
     ▼                 ▼                              ▼                     ▼
┌──────────┐   ┌──────────────┐              ┌──────────────┐      ┌──────────────┐
│ 素材管理  │   │  Bundle 层   │              │  批量引擎     │      │   质检层      │
│ data/    │   │ (bundles.py) │              │ (runner.py)  │      │ (evaluator)  │
│ assets/  │   │ 7套餐/槽位语义 │              │ 断点/重跑/成本 │      │ VLM双指标     │
│ {pid}/   │   └──────┬───────┘              └──────┬───────┘      └──────┬───────┘
│ white_*  │          │                             │                     │
│ flat_*   │          ▼                             ▼                     ▼
│ model_*  │   ┌──────────────────────────────────────────┐   ┌──────────────────┐
└──────────┘   │        Prompt 编排层（三库 + 三红线）        │   │   LLM 供应商矩阵   │
               │  compose.py 18预设 │ fashion.py 12预设      │   │ 生图: gpt-image-2 │
               │  + MARKET_VARIANTS 4市场                    │   │ 分析: DeepSeek    │
               └──────────────────────────────────────────┘   │ 质检: gemini-2.5   │
                                                          │ 兜底: 智谱 glm-4v │
                                                          └──────────────────┘
```

**数据流向**：商家素材（白底图/平铺图/模特图）→ 套餐规划（缺素材槽位自动跳过）→ 逐槽位图生图（款式一致性红线）→ VLM 质检（可用率 + Top3 打穿率）→ 按上架位置命名的成品包 →（可选）投放数据回流 → 框架库 score 沉淀。

---

## 二、分层设计详解

### 2.1 素材管理层

| 素材类型 | 目录规则 | 用途 |
|---|---|---|
| `white_*` | data/assets/{pid}/white_N.png | 标品白底图 |
| `flat_*` | data/assets/{pid}/flat_N.png | 服装平铺图（AI 试穿核心输入） |
| `model_*` | data/assets/{pid}/model_N.png | 模特照片（跨图身份锚定的基准） |

上传端点 `POST /assets/{pid}/{kind}`，同类自动编号，仅 png/jpeg/webp。**原图永远保留**——生成物全部落到 output/，绝不覆盖商家素材。

### 2.2 套餐层（Bundle = 带位置语义的清单）

核心理念：电商素材不是艺术品，是「按位置上架构图」。每个槽位定义 `pos/role/preset/size/uses/inject_top3/market/hook`，文件名直接对应上架位置。

**当前 7 个套餐：**

| 套餐 | 张数 | 场景 | 槽位结构 |
|---|---|---|---|
| `tmall_main5` | 5 | 天猫主图轮播 | 白底规范→核心卖点(注Top3)→场景→细节→信任背书 |
| `detail_8screen` | 8 | 详情页八屏 | 首屏定位→痛点→方案→证据→信任→场景→促销→收口 |
| `xhs_pack6` | 6 | 小红书种草 | 封面钩子→场景→模特→细节→痛点→合集（3:4） |
| `ab_test6` | 6 | 投放赛马 | 同构图×6 文案钩子变体（痛点/数字/对比/信任/共鸣/价格） |
| `shein_launch` | 8 | 女装跨境 | 试穿→街拍→平铺搭配→色卡→面料→尺码→欧美变体→中东变体 |
| `shein_tshirt` | 8 | SHEIN官方结构 | 模特正面→斜侧→白底正→白底背→细节四宫格→俯拍→夜景街拍→背面 |
| `full_launch` | 11 | 全量上架 | tmall_main5 + xhs_pack6 组合包 |

**计划（plan）机制**：`plan_bundle(pid, bundle, assets_dir)` 在生成前产出执行清单——缺模特图的槽位标 `runnable=False` + 原因（不阻塞整包）+ 成本预估（0.085 credits/张）+ 时长预估（18s/张）。

### 2.3 Prompt 编排层（三库 + 三红线）

**预设库 A：compose.py（18 个，标品通用）**
main_white / scene_lifestyle / model_hold / detail_closeup / pain_contrast / dimension_info / gift_box / multi_angle / selling_point / trust_badge / xhs_cover / ab_hook / screen_*×6。

**预设库 B：fashion.py（12 个，服装专用）**

| 预设 | 输入素材 | 说明 |
|---|---|---|
| ai_tryon / ai_tryon_street | flat+model | AI 试穿（棚拍 / 街拍） |
| model_front / overhead_casual / street_night | flat+model | SHEIN 官方结构逆向：正面 / 俯拍 / 夜景 |
| flat_lay / color_swatch / detail_fabric / size_chart / detail_grid4 | flat | 平铺搭配 / SKU色卡 / 面料微距 / 尺码 / 细节四宫格 |
| white_front / white_back | flat | 白底正背面（电商规范图） |

**预设库 C：MARKET_VARIANTS（4 市场本地化）**

| 市场 | 模特指令 | 场景指令 |
|---|---|---|
| us | 欧美面孔·小麦肤色 | 洛杉矶/纽约街头·明亮自然光 |
| me | 中东面孔·保守优雅（避免暴露） | 暖色奢华室内·沙漠度假感 |
| sea | 东南亚面孔·清新 | 热带绿植/海岛·高饱和 |
| eu | 欧洲面孔·冷淡高级 | 北欧极简/巴黎·低饱和电影感 |

**三红线（用户验收标准固化，TDD 锁定）：**

```python
MODEL_ANCHOR  = "模特面部必须与第二张参考图 100% 一致：同一张脸、
                 同一发型发色、同一妆容，严禁改变五官或换人。"
BODY_DIRECTIVE = "模特身材：高挑纤细、大长腿、腰臀比黄金比例、
                 肩颈线条优雅、体态挺拔，时尚大片级身材，视觉冲击力。"
ANTI_AI_SKIN  = "真实摄影质感：保留皮肤自然纹理与毛孔、发丝根根分明、
                 胶片颗粒感，禁止塑料感皮肤、过度磨皮、AI精修感。"
```

注入规则：含 model 的预设自动注入三条；market 变体注入后两条（面部不锚定——换市场人种是特性）；纯服装预设（白底/色卡）不注入。**款式一致性是所有服装预设的第一红线**：「款式/版型/剪裁/图案/颜色与平铺图 100% 一致，不得改变衣长/袖型/领型」。

### 2.4 批量引擎层（runner.py）

```
run_bundle(plan, out_dir, retry_failed=False)
  ├─ 读旧 manifest（retry 时）→ 成功槽位跳过
  ├─ 逐槽位：_slot_refs(按uses取素材) → _build_slot_prompt(预设+红线+Top3+钩子)
  │    └─ asyncio.run + async with client（每图独立事件循环，防跨 loop 复用）
  ├─ manifest.json 落盘：generated / failed / skipped / elapsed
  └─ 失败槽位带 error 摘录 → retry_failed=true 只重跑失败项
```

设计决策：**串行执行**（gpt-image-2 单张端到端 35-50s，异步任务提交后轮询不占线程；5-8 张包 5-7 分钟符合电商批量节奏。扩并发只需引擎层参数化，瓶颈在 API 侧）。

### 2.5 生图层（imagegen.py）双协议自适应

```
generate_image(cfg, prompt, out_path, reference_images=[...])
  ├─ payload: model + prompt + size(比例) + n=1 + image_urls(参考图)
  ├─ 响应自适应三分支：
  │   ├─ data[0].task_id → 异步任务模式：GET /tasks/{id} 轮询(3s) → completed取图URL下载
  │   ├─ data[0].url    → 同步url模式（旧中转站兼容）→ 下载
  │   └─ data[0].b64_json → base64 模式 → 解码落盘
  ├─ 重试：429/5xx 指数退避(2/4/8s)×3；403 quota 立即失败（重试无意义）
  └─ 参考图统一化：http(s) 透传 / 本地文件读盘转 data URL
```

供应商现状：gpt-image-2 @ apimart（异步任务模式，1k/2k/4k 档，15 种比例）。

### 2.6 质检层（evaluator.py）

- **双指标**：`usable_rate`（可用率，≥80 达标）+ `top3_coverage`（Top3 打穿率，卖点在画面中视觉可见地传达，≥40 达标）——可用率恒高的假绿时代已用打穿率终结（旧图 5.6% vs 流水线 50%）
- **多票表决**（EVAL_VOTES=3）：hit 多数决 / score 中位数 / issues 并集——抗 VLM 概率性波动（实测同图 3 票 2/2/0 来回跳）
- **双端点容灾**：主端点 403 quota → 立即切兜底（智谱 glm-4v-flash），不烧退避时间
- **健壮性**：200 但 body 非 JSON（SSE/网关页）按可重试处理，不裸崩
- 参数纪律：`stream:false`（apimart 默认 SSE）+ `max_tokens:2000`（gemini 800 截断 JSON）+ `temperature:0`

### 2.7 数据闭环（L10-L11）

```
投放数据 CSV（image,impressions,clicks,orders,carts）
  → L10 importer 入库
  → L11 iterate 归因：winners（为什么赢）/ losers（为什么输）
  → 框架库 score 回流：胜率排序 → 下个 SKU 生成时优先用高胜率构图
  → 低胜率框架自动淘汰
```

这就是「素材版小单快返」：小成本套餐测图 → 数据好的构图追量复用。

### 2.8 编排层（Dify v3 工作流）

10 节点画布（已发布）：`开始 → 前八层分析链(L1→L8) → 生成商品图(mode可选) → VLM质检 → 解析报告 → 可用率≥80%且打穿率≥40%? → 达标出图 / 未达标→DeepSeek优化建议`

- 失败语义诚实：上游脚本非零退出 → API 502 → Dify 节点 retry → failed（「生图 0 张仍 succeeded」的假绿灯已消灭）
- DSL 程序化构建（build_v2/v3.py）+ 11 项断言自检（边格式/timeout/ELSE case/连通性）——DB 是唯一真源，防仓库版腐化
- launchd 每日 9 点定时触发（TCC 双层拦截已解决：权威源在仓库，部署副本在 ~/bin）

---

## 三、十一层方法论映射（系统骨架的理论来源）

| 层 | 方法论 | 系统实现 |
|---|---|---|
| L1-L2 | 产品画像 / 竞品分析 | /analyze 链（DeepSeek），产 selling_points 表 |
| L3-L4 | 图库 / 拆解 | 商家素材 + VLM 逆向分析（SHEIN 官方 9 图 → 6 预设） |
| L5 | 框架库 | frameworks.json，score 唯一入口，胜率排序 |
| L6-L7 | 用户反馈 / 卖点排序 | feedback 抽取 → Top3 红线（注入质检与生成） |
| L8 | 设计 brief | design_brief_{pid}.json（分析链产物） |
| L9 | 出图 | Bundle 套餐 + 三红线 prompt 编排 |
| L10 | 投放导入 | importer + ads CSV |
| L11 | 归因迭代 | iterator → score 回流闭环 |

---

## 四、工程规范（全系统生效）

1. **TDD 铁律**：174 tests，所有功能 RED-GREEN-REFACTOR 实现
2. **失败码透传**：脚本非零退出 → 502，错误必须如实上抛
3. **断言自检**：DSL 构建/导出脚本尾部断言（边格式/timeout/比较符/连通性），失败即退出
4. **密钥纪律**：.env 不入库（曾泄露→轮换→filter-repo 历史净化，全流程有 skill 沉淀）
5. **供应商容灾矩阵**：生图（apimart 主）/ 分析（DeepSeek 官方）/ 质检（gemini-2.5-flash 主 + glm-4v-flash 兜底）——三链路独立供应商，单点故障不传染
6. **本地中继**（~/bin/dify-pipeline/apimart_relay.py，8008）：hermes 视觉等不支持代理的客户端 → 直连 8008 → 强制模型改写+stream:false → 经 7897 → apimart

---

## 五、真实运行数据（截至 2026-08-17）

| 案例 | 套餐 | 结果 | 质检 |
|---|---|---|---|
| SHEIN 官方黄 T（product_3 输入） | shein_tshirt | 8/8，376s | 白底 10/10 · 细节四宫格 10/10 · 夜景 9.5/10 |
| 三红线重跑版 | shein_tshirt | 8/8，376s | Gemini 联判：与参考同脸 / 跨槽位同脸 / 身材一致 ✓ |
| 法式碎花连衣裙 | shein_launch | 8/8，420s | 款式 100% 一致 · 中东市场适配 ✓ |
| 保温杯 | tmall_main5 | 5/5，305s | 卖点图视觉复核可商用 · 打穿率 50% |

成本基准：0.085 credits/张（1k 档）≈ 5 分钱；单 SKU 全量包 ≈ 6 毛钱。

---

## 六、已知限制与路线图

**如实声明的限制**：
- 手部细节与面料微纹理仍有 AI 痕迹（高端线建议 AI 出图 + 真人精修混合）
- 尺码指南图含 EDIT 数值占位（设计如此，需人工填真实尺寸）
- 并发=1（瓶颈在生图 API 侧，引擎已按异步模型设计可扩）
- 跨图人脸一致性依赖 prompt 锚定，极限情况（大角度侧脸→正面）仍有漂移

**路线图**：
1. B5：整包 zip 导出 + 清单 CSV + 按包质检报告聚合
2. SKU 颜色矩阵真跑（一款多色 → N×构图槽位展开已实现，待 E2E）
3. 模特库：多个持证模特照建档，按品类/市场路由（替代单一 model_1）
4. 视觉密码：从 winners 图反向提炼构图要素自动入库（L11 深化）

---

*维护规则：改套餐/预设/红线必须先改测试（TDD）；DSL 改动走 build_v2/v3.py 程序化路径 + 断言自检；本文档随重大 commit 同步更新。*
