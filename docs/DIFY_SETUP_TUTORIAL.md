# Dify 工作流搭建保姆级教程

> 目标：本地 Dify 编排「生图 → VLM质检 → 视频合成」全链路，配完截图就是面试核心素材。
> 前置：`~/Desktop/dify-pipeline` 的 FastAPI 已跑在 `http://127.0.0.1:8100`（health 返回 ok）。

---

## 0. 前置检查（30秒）

```bash
curl http://127.0.0.1:8100/health
# 期望：{"ok":true,"service":"dify-pipeline"}

docker ps --format '{{.Names}}' | grep docker-  # Dify 容器组应已启动
```

## 1. 打开 Dify

浏览器访问 **http://127.0.0.1**（Dify nginx 默认 80 端口）。

首次进入要求设置管理员账号：
1. 填邮箱（如 admin@test.com）、昵称、密码（≥8位）
2. 点「设置」→ 进入主界面

## 2. 配置模型（DeepSeek，用于建议节点）

右上角头像 → **设置** → **模型供应商**：

**方式一：直接用 DSL 里的模型占位**
工作流里 LLM 节点用的 `deepseek-chat`，需要配一个 DeepSeek 或任意 OpenAI 兼容供应商：
1. 模型供应商列表找到 **DeepSeek**（或 OpenAI-API-compatible）
2. API Key 填你的 DeepSeek key（没有就用 OpenAI-API-compatible 方式接入中转站）
3. OpenAI-API-compatible 接中转站（推荐，零新注册）：
   - 模型名称：`deepseek-v3.2`
   - API Key：中转站 key（同 dify-pipeline/.env 的 ARK_API_KEY）
   - API endpoint URL：`https://yunwu.ai/v1/chat/completions`
   - ⚠️ 若 Docker 代理未配，这个 URL 可能连不通——见第 6 节「常见坑」

## 3. 导入工作流（推荐，免去手画）

1. 主界面点 **「创建空白应用」→「导入 DSL 文件」**
2. 选择 `~/Desktop/dify-pipeline/dify/workflow.yml`
3. 导入后看到完整画布：开始 → 生成商品图 → VLM质检评分 → 解析评分报告 → 可用率≥80%? →(是) 合成视频 / (否) Prompt优化建议
4. **截图整个画布**（面试素材）

## 4. 手动搭一遍（理解每个节点，面试被问能答上）

创建空白应用 → 类型选 **「工作流」** → 命名「AI商品图视频流水线」。

### 4.1 环境变量（先配好，后面节点引用）

画布右上角 ⚙️ → 环境变量：
- 名称 `API_BASE`，值 `http://host.docker.internal:8100`
- ⚠️ **不要填 127.0.0.1**！Dify 跑在 Docker 容器里，容器内的 127.0.0.1 是容器自己

### 4.2 [开始] 节点
- 输入变量：`product_id`（文本，必填）、`gen_limit`（数字，默认2）

### 4.3 [HTTP 请求] 生成商品图
- 方法 POST，URL `{{#env.API_BASE#}}/generate`
- Body 类型 JSON：`{"limit": {{#start.gen_limit#}}}`
- 超时：读取超时调到 **3600**（生图 12 张约 1-2 分钟，默认 10s 会超时）

### 4.4 [HTTP 请求] VLM质检评分
- 方法 POST，URL `{{#env.API_BASE#}}/evaluate`
- 超时同样调大（12 张图评分约 1 分钟）

### 4.5 [代码] 解析评分报告
- Python3，入参 `body` ← 上节点 `body`
- 代码（从 stdout 提取可用率）：

```python
def main(body: str) -> dict:
    rate, top_issue = None, ""
    for line in (body or "").splitlines():
        if "总体可用率" in line:
            try:
                rate = float(line.split("总体可用率")[1].split("%")[0].strip())
            except Exception:
                pass
        if "top_issue=" in line:
            top_issue = line.split("top_issue=")[1].strip()
    return {"rate": rate if rate is not None else -1,
            "passed": rate is not None and rate >= 80,
            "top_issue": top_issue}
```
- 输出：rate(number)、passed(string)、top_issue(string)

### 4.6 [条件分支] 可用率≥80%?
- 条件：`parse-report / rate` **>=** `80`

### 4.7 分支「是」→ [HTTP 请求] 合成视频
- POST `{{#env.API_BASE#}}/video/{{#start.product_id#}}`

### 4.8 分支「否」→ [LLM 节点] Prompt优化建议
- 模型选你配好的任意 chat 模型
- System Prompt：
  > 你是AI生图质检专家。图片可用率低于80%，最高频问题是：{{#parse-report.top_issue#}}。
  > 请给出 3 条具体可执行的生图 Prompt 修改建议（中文，每条一行）。

### 4.9 [结束] ×2
- 视频分支输出 `make-video/body`
- 建议分支输出 `llm-advice/text` + `rate` + `top_issue`

## 5. 运行验证

点右上角「运行」，输入 product_id=`P001`，gen_limit=`2`。

期望 2-4 分钟后：
- 走「是」分支 → 输出里有 `P001.mp4` 生成日志
- 或故意把阈值改 95 逼走「否」分支 → 输出 3 条 Prompt 建议

## 6. 常见坑（实战验证，全部踩过）

| 症状 | 原因 | 解法 |
|------|------|------|
| HTTP 节点 `connection refused` | URL 用了 127.0.0.1 | 改 `host.docker.internal:8100` |
| 导入 DSL 后 Run Steps=0（静默空跑） | **边字段用错**：`sourceID/targetID` 是旧格式 | 必须用 `source/target` + `data.sourceType/targetType`（对照 api/tests/fixtures 的官方样例） |
| pydantic 校验 `timeout` 报错 | HTTP 节点 timeout 不能是整数 | 用对象 `{connect, read, write}`（毫秒） |
| if-else 校验 `comparison_operator` 报错 | `>=` 不是合法字面量 | Dify 用 unicode 符号 `≥` `≤` `≠` |
| if-else 校验 `logical_operator missing` | ELSE 分支也要该字段 | 每个 case 都补 `logical_operator: and` |
| LLM 节点报 `plugin not found` | Dify 1.x 模型全走插件系统 | 装 `langgenius/openai_api_compatible` 插件（marketplace API 直装最快） |
| 容器访问外网 `Network is unreachable` | 宿主 VPN 是应用层代理 | compose `x-shared-env` 加 `HTTP_PROXY=http://host.docker.internal:7897` |
| 加代理后内网服务 502 | **小写 no_proxy 覆盖大写 NO_PROXY**（镜像 entrypoint 默认值） | 小写 no_proxy 也写全内网域名+网段，且 `--force-recreate`（compose 不重建未变更容器） |
| URL 导入 DSL 一直 404 | ssrf_proxy 的 squid 把所有代理请求转给 sandbox 父节点 | 用文件上传方式（本仓库 dify/serve_dsl.py 起 CORS 服务+浏览器注入） |
| 重建容器后 502 | nginx 缓存了 api 旧 IP | `docker restart docker-nginx-1` |
| 模型凭据验证 `Invalid URL .../chat/completions/chat/completions` | endpoint_url 填了完整路径 | 只填到 `https://yunwu.ai/v1`，插件自动拼 |
| 评分大量 score=0 | VLM 网络抖动解析失败被误判 | 已修：解析失败纳入重试循环（见 tests/test_evaluator_resilience.py） |
| LLM 节点 403 insufficient_quota | 中转站配额耗尽 | 账号充值或换 key，代码无需改动 |

## 7. 定时触发（可选）

Dify 工作流本身不带定时器，用 macOS launchd（见 `cron/com.sunnyworld.dify-pipeline.plist`）：

```bash
launchctl load ~/Library/LaunchAgents/com.sunnyworld.dify-pipeline.plist
```

每天 9:00 自动以 P001 跑一轮全链路。Dify 应用 API 密钥在「访问 API → API 密钥」页面生成后填入 plist。

## 8. 面试一句话讲清架构

「我用 Dify 编排了商品营销素材生产链路：FastAPI 把 Python 生图/质检/合成脚本服务化，Dify 工作流通过 HTTP 节点串起全流程，VLM 质检评分低于 80% 时自动走 LLM 节点产出 Prompt 优化建议形成闭环，launchd 定时触发 Dify API 实现无人值守。」


---

## 7. 工作流 v2（十一层编排版，当前主推）

v2 的 DSL 在 `dify/workflow_v2.yml`，由 `dify/build_v2.py` 程序化构建（改需求改脚本，别手改 yml）。

### 与 v1 的区别

| 节点 | v1 | v2 |
|---|---|---|
| 前八层分析链(L1→L8) | ❌ 无（直接生图） | ✅ 前置 analyze，产出 Top3 卖点红线 |
| 生图模式 | 固定 styles | `mode` 可选 styles / screens（八屏视觉逼单） |
| 质检分支 | 仅可用率≥80% | 可用率≥80% **AND** Top3打穿率≥40%（无Top3数据不卡） |
| 「否」分支 LLM | 与生图同中转站（同生共死） | DeepSeek 官方直连（容灾） |
| 失败语义 | 错误吞没（0张图也succeeded） | 502 透传 → 节点 retry → failed 如实上抛 |

### 运行
```
product_id=P001, gen_limit=1, mode=styles（或 screens）
```
红路预期（配额未恢复时）: analyze 成功(~50-70s) → 生成商品图 failed —— 这是**正确行为**，证明失败如实暴露。
绿路预期: 全链 succeeded，outputs 含 coverage（Top3打穿率%）。

### 维护命令
```bash
.venv/bin/python dify/export_graph.py   # DB → dify/workflow.yml（v1 修正版回写）
.venv/bin/python dify/build_v2.py       # v1 → dify/workflow_v2.yml（含11项断言自检）
```

### 管理凭据
- console 账号: admin@dify-pipeline.local（密码在 macOS 钥匙串 `dify-console`）
- cron 用的 app key: .env 的 DIFY_API_KEY（v2 app）
