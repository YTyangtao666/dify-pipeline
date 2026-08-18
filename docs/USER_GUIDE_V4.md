# v4 技能包一键生成 · 使用教程（保姆级）

> 三个入口任选：控制台 UI（最简单）/ Dify 画布（可视化）/ API 直调（自动化）
> 前置：api_server 运行中（端口 8100）

---

## 一、控制台 UI（推荐，点鼠标）

1. 浏览器打开 **http://127.0.0.1:8100/console**
2. 左上「技能包」下拉选一个（如 *SHEIN官方休闲风（7槽位）*）
3. 「商品ID」填素材目录名（如 `T001`，需已上传平铺图/模特图）
4. 点 **▶ 开始生成**
5. 右侧任务卡实时显示：状态徽章（排队/运行中/完成/失败）+ 进度条 + 已生成张数
6. 完成后底部**图片墙**自动加载全部产物（00A 商品特写 / 00B 模特三视图 / 01-07 套图）
7. 有失败项时：勾选「只重跑失败槽位」再点开始 → 只补失败的那几张

### 启动服务（如果 8100 没起）

```bash
cd ~/Desktop/dify-pipeline
.venv/bin/python scripts/api_server.py
```

---

## 二、Dify 画布 v4（可视化工作流）

### 1. 启动 DSL 静态服务（一次性）

```bash
cd ~/Desktop/dify-pipeline/dify
../.venv/bin/python serve_dsl.py   # 端口 8200，带 CORS
```

### 2. 导入 v4 工作流（一次性）

1. 打开 http://127.0.0.1/apps → 登录（admin@dify-pipeline.local / Dify@2026admin）
2. 左上 **「创建空白应用」→「导入 DSL 文件」**
3. 选择 **「从 URL 导入」**，粘贴：
   ```
   http://127.0.0.1:8200/workflow_v4.yml
   ```
4. 点「创建」，得到应用 **「AI电商图工厂 v4 · 技能包一键生成」**

### 3. 跑一次

1. 打开应用 → 右上 **「运行」**
2. 填两个参数：
   - `skill_id`：`shein_official_v1`
   - `product_id`：`T001`
3. 点「开始运行」
4. 节点依次亮起：**开始 → 提交生成任务 → 轮询至完成（约 8 分钟，每 30 秒查一次）→ 完成**
5. 结束节点输出：`state`（done）、`image_count`（张数）、`images`（可点击的图片 URL 列表，浏览器直接打开看图）

> 注意：轮询节点最长等 8.5 分钟；若任务超时，去控制台 UI（/console）看任务状态，生成仍在后台继续。

---

## 三、API 直调（自动化/脚本）

```bash
# 1. 异步提交 → 立即返回 task_id（不阻塞）
curl -X POST http://127.0.0.1:8100/generate/skill/async \
  -H 'Content-Type: application/json' \
  -d '{"skill_id":"shein_official_v1","product_id":"T001"}'
# → {"task_id":"t_xxx","poll":"/tasks/t_xxx"}

# 2. 轮询（2 秒一次即可）
curl http://127.0.0.1:8100/tasks/t_xxx
# → {"state":"running","progress":"3/9",...} → {"state":"done","images":[{url},...]}

# 3. 看图（浏览器直接打开）
# http://127.0.0.1:8100/file?path=output/bundles/T001_shein_official_v1/T001_01_户外街拍穿搭图.png

# 失败补跑
curl -X POST http://127.0.0.1:8100/generate/skill/async \
  -H 'Content-Type: application/json' \
  -d '{"skill_id":"shein_official_v1","product_id":"T001","retry_failed":true}'
```

---

## 常见问题

| 现象 | 处理 |
|---|---|
| 提交返回 400「缺素材」 | 先传商品素材：`POST /assets/T001/flat`（multipart，字段 file） |
| 状态一直 queued | 看服务日志 `/tmp/dify-api.log`；后台线程崩溃会写 failed+error |
| Dify 轮询节点 timeout | 生成超 8.5 分钟（网络慢）；任务仍在跑，稍后用 `/tasks` 查 |
| 图片墙某张 404 | 该槽位生成失败，勾 retry 重跑 |
