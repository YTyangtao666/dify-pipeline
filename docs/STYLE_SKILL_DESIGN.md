# 多样化风格技能包系统 · 设计

## 核心范式转变

```
现有系统（写死）:  预设/套餐 → 硬编码 30 个 → 只能出已定义的图型
元工作流（学习）:  10张样例图 → [风格学习器] → 技能包(.json) → 新商品素材 → 一键批量生成
```

## 三阶段设计

### 阶段1：学习（/skills/learn）
```
输入: 3-20 张样例电商图（松散上传，不需要标注）
     + 可选: 风格名、品类提示（服装/标品/混合）

处理: 逐图 VLM 逆向分析（gemini-2.5-flash）
  每图产出: {type, composition, lighting, pose, framing,
             input_deps(推断这张图需要什么输入: 平铺图?模特?白底?),
             prompt_hint(生成这类图的关键指令)}

聚合: 1 次 LLM 调用把 N 份分析 → 槽位结构
  - 同类型图合并为一个槽位（取共性构图要素）
  - 不同类型 = 不同槽位（role/preset/size/input_deps）

输出: 技能包 JSON
```

### 阶段2：固化（技能包格式）
```json
{
  "skill_id": "shein_casual_v1",
  "name": "SHEIN休闲风",
  "learned_from": ["图指纹..."],
  "created": "...",
  "slots": [
    {"pos": 1, "role": "模特正面生活图", "size": "3:4",
     "input_deps": ["flat", "model"],
     "template": "参考平铺图...{title}...顶部柔光+前方补光...",
     "reference_images": ["slot样例图路径(少样本质检用)"]}
  ],
  "quality_bar": {"min_usable_rate": 80, "style_keywords": [...]}
}
```
技能包存 `data/skills/{skill_id}.json`——像 skill 一样可复制、可分享、可版本化。

### 阶段3：应用（/generate/skill）
```
输入: skill_id + product_id
     素材任意组合（有啥用啥）: white/flat/model/onbody(上身照) + 卖点文字 + 产品数据

处理: 技能包 slots × 商品可用素材
  - input_deps 满足 → 可跑（prompt = template + 商品信息注入 + 三红线(服装类)）
  - 不满足 → 跳过并报告（不阻塞）
  - 文字卖点/产品数据 → 注入 template 的 {selling_points}{price} 占位符

输出: 现有 runner 批量执行 → output/bundles/{pid}_{skill_id}/
```

## 灵活性保障（「不要写死」）
1. 槽位结构从样例动态学习，非预定义
2. 输入素材类型开放集合（white/flat/model/onbody/任意），按 input_deps 声明式匹配
3. template 带占位符（{title}{selling_points}{price}{color}），文字数据有什么注入什么
4. 技能包是数据不是代码——新风格=上传新样例学习，零代码改动

## 实现任务（TDD）
- S1 style_learner.py: 逐图分析(VLM) + 聚合成槽位 —— ~6 tests(mock VLM)
- S2 skill_pack.py: 技能包 save/load/校验/版本 —— ~4 tests
- S3 API: /skills/learn(上传样例) /skills/list /generate/skill —— ~5 tests
- S4 E2E: SHEIN 9图 → 学习 → 技能包 → T001素材一键生成 8+ 图

复用: runner.py 批量引擎 / fashion.py 三红线 / evaluator.py 质检 全部不动。
