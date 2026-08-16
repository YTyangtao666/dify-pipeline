# 工作流实用性与可用性修复计划（闭环版）

> **For Hermes:** 按任务顺序执行，每任务完成即 commit+push（git -c http.proxy=http://127.0.0.1:7897 push，报 tlsv1 时加 -c http.sslVersion=tlsv1.2）。禁止 write_file 写 .env（只用 terminal echo >>）。禁止任何假数据/模拟。

**Goal:** 让 Dify 工作流从「演示品」变成「可信交付系统」：密钥不泄露、定时真触发、失败真暴露、十一层真编入、双端点真容灾。

**架构逻辑闭环（为什么是这个顺序）:**

```
Phase 0 安全止血 ──┐
  T1 密钥轮换      │  新 key 必须先存在，T2 的触发器才有东西可引用
  T2 launchd 修复 ─┤  T2 用 T1 的新 key；TCC 修好后每日触发恢复
Phase 1 链路诚实  ─┤  T3/T4 是 Phase 2 的前置：v2 工作流的分支语义依赖 502 语义和 coverage 输出
  T3 失败码透传    │
  T4 coverage 输出 ─┤
Phase 2 编排重建  ─┤  T5 导出正确图 → T6 建 v2 → T7 凭据容灾 → T8 发布+切换 → T9 清死壳
Phase 3 闭环验证  ─┘  T10 红路 E2E（今天就能跑）+ 绿路门禁（等配额）+ 文档
```

每个 Phase 的产物是下一个 Phase 的输入；T10 同时验证全部前序任务——任一环节造假，E2E 立刻暴露。这就是闭环。

**Tech Stack:** FastAPI/TestClient(httpx)、pytest、psql(docker exec)、Dify 1.9 console API、launchd、git filter-repo(可选)。

---

## 审查结论回顾（已全部实证，非猜测）

| # | 问题 | 证据 |
|---|------|------|
| P0-1 | `REMOVED` key 泄露在 public 仓库 `scripts/05_dify_cron.sh` | git log -S 定位 fe7efcc；GitHub API 200 |
| P0-2 | launchd 从未成功：TCC 拦 Desktop 下脚本 | launchctl 状态 126；日志 "Operation not permitted" |
| P1-1 | 仓库 `dify/workflow.yml` 是旧格式（sourceID/整数timeout/'>='），导入必空跑；正确版只在 DB（ec72f9e7） | 两侧对比已读 |
| P1-2 | 错误吞没：02 全失败 exit 3，但 api_server.run() 无视 returncode 恒 200 | api_server.py:20-22；昨夜 run 生图 0 张仍 succeeded |
| P1-3 | 工作流只有 4 步，十一层核心（analyze/mode/L10-L11）未编入 | graph 节点清单已读 |
| P2-1 | 「否」分支 LLM 与生图同一中转站(yunwu)，配额死→双瘫 | 15 日 5 次 failed 全在 llm-advice，403 |
| P2-2 | 阈值 80 失去区分度（恒 100%），coverage(1/18) 未消费 | eval_report.json overall |
| P3 | 2 个死壳 app（a7033fe9/6d432fa3 各 0 workflow）；/report 端点无人用 | DB 查询 |

---

### Task 1: 密钥轮换 + cron 脚本脱敏（P0-1）

**Objective:** 旧 key 作废（历史泄露立即失效），新 key 只存 .env，仓库不再含明文。

**Files:**
- Modify: `scripts/05_dify_cron.sh`（改为 source .env）
- Modify: `~/Desktop/dify-pipeline/.env`（terminal echo 追加 DIFY_API_KEY，禁 write_file）

**Step 1: 查 api_tokens 表结构**（插入前必看，不猜列名）

```bash
docker exec docker-db-1 psql -U postgres -d dify -c "\d api_tokens"
```

**Step 2: 生成新 key 并入库，删除旧 key**

```bash
NEWKEY="app-$(openssl rand -hex 12)"
docker exec docker-db-1 psql -U postgres -d dify -c \
  "DELETE FROM api_tokens WHERE token='REMOVED';"   # 旧 key 全值以 scripts/05_dify_cron.sh 内实际值为准
# 按Step1实际列名 INSERT（id 用 gen_random_uuid()，app_id='0851b74d-99b3-4e1c-93cf-ea3647dae88a'，token、type、created_at 补齐 NOT NULL 列）
docker exec docker-db-1 psql -U postgres -d dify -c \
  "INSERT INTO api_tokens (id, app_id, token, type, created_at, last_used_at)
   VALUES (gen_random_uuid(), '0851b74d-99b3-4e1c-93cf-ea3647dae88a', '$NEWKEY', 'app', now(), NULL);"
echo "DIFY_API_KEY=$NEWKEY" >> ~/Desktop/dify-pipeline/.env
```

**Step 3: 验证新 key 可用、旧 key 已死**

```bash
curl -s -X POST http://127.0.0.1/v1/info -H "Authorization: Bearer $(grep DIFY_API_KEY ~/Desktop/dify-pipeline/.env | cut -d= -f2)" | head -c 200
# 期望：200 含 app 名；用旧 key 再试 → 401
```

**Step 4: cron 脚本脱敏**：删掉 `DIFY_API_KEY="app-..."` 硬编码行，改为
```bash
set -a; source "$(dirname "$0")/../.env" 2>/dev/null || source ~/Desktop/dify-pipeline/.env; set +a
```

**Step 5: commit + push**（消息: `fix(security): 轮换泄露的Dify API key,cron改读.env`）

**Step 6（可选，用户确认后）:** git 历史清除
```bash
pip install git-filter-repo
cd ~/Desktop/dify-pipeline
echo 'REMOVED==>REMOVED' > /tmp/replace.txt
git filter-repo --replace-text /tmp/replace.txt --force
git remote add origin git@github.com:YTyangtao666/dify-pipeline.git
git -c http.proxy=http://127.0.0.1:7897 push --force origin main
```
注意：轮换后旧 key 已死，此步属加固非必须；filter-repo 会删 origin 需重加。

---

### Task 2: launchd TCC 修复（P0-2）

**Objective:** 定时任务真正能执行。原理：launchd 的 bash 无 Desktop 访问权，把启动脚本挪出 TCC 保护目录。

**Files:**
- Create: `~/bin/dify-pipeline/run.sh`（包装器，不进仓库）
- Modify: `~/Library/LaunchAgents/com.sunnyworld.dify-pipeline.plist`

**Step 1:**

```bash
mkdir -p ~/bin/dify-pipeline
cat > ~/bin/dify-pipeline/run.sh <<'EOF'
#!/bin/bash
# launchd 包装器：绕开 Desktop TCC，转发到仓库内真实脚本
exec /bin/bash /Users/Admin/Desktop/dify-pipeline/scripts/05_dify_cron.sh "${1:-P001}"
EOF
chmod +x ~/bin/dify-pipeline/run.sh
```

等一下——TCC 拦的是「launchd 的 bash 读 Desktop 下文件」，包装器仍要读 Desktop 脚本，可能同样被拦。**实测为准**：先 kickstart 验证；若仍 126，则把 05_dify_cron.sh 整体复制到 ~/bin/dify-pipeline/cron.sh（仓库保留权威版，bin 里是部署副本，脚本头注明"部署副本勿改，权威源见仓库"），plist 指向副本。

**Step 2: 更新 plist 并重载**

```bash
# plist ProgramArguments 的脚本路径改为 /Users/Admin/bin/dify-pipeline/run.sh（或副本路径）
launchctl bootout gui/$(id -u)/com.sunnyworld.dify-pipeline 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sunnyworld.dify-pipeline.plist
launchctl kickstart -k gui/$(id -u)/com.sunnyworld.dify-pipeline
sleep 90; tail -5 /tmp/dify-pipeline-cron.log
```

**验证（三选一即算过）:**
- 日志出现 `[date] trigger P001`（脚本真正执行了）
- `launchctl list | grep dify` 状态列非 126
- DB 新增 workflow_runs 行：`SELECT created_at,status FROM workflow_runs ORDER BY created_at DESC LIMIT 1;`

注：run 最终可能 failed（配额）——不影响本任务验收，本任务修的是「能不能执行」，不是「执行成不成功」。

**Step 3:** 若采用部署副本方案，仓库加 `docs/DEPLOY_NOTE.md` 说明权威源与副本关系，commit+push。

---

### Task 3: TDD——失败码透传（P1-2 核心）

**Objective:** 脚本非零退出 → API 返回 502 → Dify HTTP 节点失败 → 工作流如实 failed。消灭「生图 0 张仍 succeeded」。

**Files:**
- Create: `tests/test_api_server.py`
- Modify: `scripts/api_server.py:20-22`（run() 增加 fail_fast 参数或新增 respond 辅助）

**Step 1: 写失败测试**

```python
# tests/test_api_server.py
from fastapi.testclient import TestClient
from scripts import api_server

class _R:
    def __init__(self, rc): self.returncode = rc; self.stdout = "out"; self.stderr = "err"

def test_nonzero_exit_maps_502(monkeypatch):
    monkeypatch.setattr(api_server.subprocess, "run", lambda *a, **k: _R(3))
    r = TestClient(api_server.app).post("/generate?limit=1")
    assert r.status_code == 502 and r.json()["code"] == 3

def test_zero_exit_maps_200(monkeypatch):
    monkeypatch.setattr(api_server.subprocess, "run", lambda *a, **k: _R(0))
    r = TestClient(api_server.app).post("/generate?limit=1")
    assert r.status_code == 200
```

**Step 2:** `pytest tests/test_api_server.py -v` → 期望 FAIL（现恒 200）

**Step 3: 最小实现**（api_server.py）

```python
def respond(res: dict) -> JSONResponse | dict:
    return JSONResponse(res, status_code=502) if res["code"] != 0 else res
# 每个端点 return respond(run([...]))
```

**Step 4:** 全量 `pytest tests/ -q` → 期望 120 passed（118+2）

**Step 5:** 重启 8100 服务（改后必重启，不等催）：
```bash
kill $(lsof -t -iTCP:8100 -sTCP:LISTEN); sleep 1
cd ~/Desktop/dify-pipeline && nohup .venv/bin/python scripts/api_server.py >> /tmp/dify-api.log 2>&1 &
curl -s http://127.0.0.1:8100/health
```

**Step 6:** commit+push（`feat: API失败码透传——脚本非零退出返回502(TDD)`）

**回滚保护:** 502 只在 code≠0 时触发；报告类 /report 不变。

---

### Task 4: TDD——03 输出 coverage 摘要行（P2-2 前置）

**Objective:** 03 脚本 stdout 增加 `top3_coverage=xx.x%` 行，供 Dify 代码节点解析；无 Top3 数据时输出 `top3_coverage=none`。

**Files:**
- Modify: `scripts/03_eval_images.py:87` 附近
- Create/append: `tests/test_eval_summary.py`

**Step 1: 失败测试**

```python
# 从 scripts.pipeline.evaluator 或 03 提取的 coverage_pct 函数
def test_coverage_pct_full():
    overall = {"top3_coverage": {"a": 2, "b": 1},
               "items": [{"top3_hits": [{"hit": True}] * 3}, {"top3_hits": [{"hit": False}] * 3}]}
    assert abs(coverage_pct(overall) - 50.0) < 0.01   # 3/6

def test_coverage_pct_none():
    assert coverage_pct({"top3_coverage": {}, "items": [{"top3_hits": []}]}) is None
```

**Step 2:** FAIL → **Step 3:** 在 evaluator.py 实现 `coverage_pct(overall) -> float | None`（分母 = Σ len(item.top3_hits)，为 0 → None），03 主流程打印：
```python
cov = coverage_pct(overall)
print(f"[03] top3_coverage={'none' if cov is None else f'{cov:.1f}%'}")
```
**Step 4:** 全量 pytest 全绿 → **Step 5:** 用现存 eval_report.json 实算一遍，期望 ≈5.6%（1/18，方法论证据）。**Step 6:** commit+push。

---

### Task 5: 从 DB 导出正确 graph 回写仓库（P1-1）

**Objective:** 仓库 yml 恢复「导入即能跑」，消灭毒药格式。

**Files:**
- Create: `dify/export_graph.py`
- Overwrite: `dify/workflow.yml`（v1 修正版；v2 见 Task 6）

**Step 1:**

```python
# dify/export_graph.py —— DB graph → 标准 DSL yaml
import subprocess, json, yaml
q = "SELECT graph FROM workflows WHERE id='ec72f9e7-5384-4591-8b28-aeb054adf9a5';"
raw = subprocess.run(["docker","exec","docker-db-1","psql","-U","postgres","-d","dify","-t","-A","-c",q],
                     capture_output=True, text=True).stdout.strip()
graph = json.loads(raw)
dsl = {"kind":"app","version":0.1.5,
       "app":{"name":"AI商品图视频流水线","mode":"workflow",
              "description":"商品图生成 → VLM质检 → 自动视频合成 全链路",
              "icon":"🤖","icon_background":"#FFEAD5","use_icon_as_answer_icon":False},
       "workflow":{"graph":graph,"features":{"file_upload":{"enabled":False}},
                   "environment_variables":[{"id":"api-base-env","name":"API_BASE",
                     "value":"http://host.docker.internal:8100","value_type":"string"}],
                   "conversation_variables":[]}}
open("dify/workflow.yml","w").write(yaml.safe_dump(dsl, allow_unicode=True, sort_keys=False))
```

**Step 2: 断言自检**（脚本尾部）：edges 全含 source/target、3 个 http 节点 timeout 是 dict、比较符是 ≥。任一失败即报错退出。

**Step 3:** 删除仓库 yml 中 DB 没有的死代码残留，commit+push（`fix: workflow.yml回写DB正确格式(source/target+timeout对象+≥)`）。

---

### Task 6: 构建工作流 v2——十一层编入画布（P1-3 + P2-2）

**Objective:** 画布体现方法论：先分析后生图、mode 可选、coverage 进分支、失败即红。

**新 graph 结构（在 Task 5 导出的 graph 基础上程序化改，不手搓）：**

```
start(product_id, gen_limit, mode[styles|screens])
 → analyze[http POST {API_BASE}/analyze/{product_id}?full=false]   ← L1→L8，Top3 红线
 → gen-images[http POST /generate body {"limit":{gen_limit},"mode":{mode}}]
 → eval-images[http POST /evaluate]
 → parse-report[code]  ← 新增解析 top3_coverage 行，输出 rate/coverage/coverage_pass/top_issue
    coverage_pass 规则: coverage 为 none → "true"（styles 模式无 Top3 表，不卡）；否则 ≥40% 为 "true"
 → check[if-else]: rate ≥ 80 AND coverage_pass == "true"
    ├─ true  → make-video[POST /video/{pid}] → end-video（输出 result + coverage）
    └─ false → llm-advice[deepseek-chat 官方直连，prompt 注入 top_issue+coverage]
              → end-advice（输出 advice/rate/coverage/top_issue）
```

**改动全部程序化**（dify/build_v2.py）：
- start.variables 加 `{variable: mode, type: select, options: [styles, screens], default: styles}`
- 新增 analyze 节点（复制 gen-images 节点改 url/method，位置 x=350，其余右移 300）
- gen-images body.data 改 `'{"limit": {{#start.gen_limit#}}, "mode": "{{#start.mode#}}"}'`
- parse-report code 改（完整代码进 build_v2.py 字符串）：

```python
def main(body: str) -> dict:
    rate, cov, top_issue = None, None, ""
    for line in (body or "").splitlines():
        if "总体可用率" in line:
            try: rate = float(line.split("总体可用率")[1].split("%")[0].strip())
            except Exception: pass
        if "top3_coverage=" in line:
            v = line.split("top3_coverage=")[1].strip()
            cov = None if v == "none" else float(v.replace("%", ""))
        if "top_issue=" in line:
            top_issue = line.split("top_issue=")[1].strip()
    cov_pass = "true" if (cov is None or cov >= 40) else "false"
    return {"rate": rate if rate is not None else -1,
            "coverage": cov if cov is not None else -1,
            "coverage_pass": cov_pass, "top_issue": top_issue}
```

- check-rate conditions 改两条（and）：rate≥'80'（number）；coverage_pass = 'true'（string，contains）
- llm-advice model 改 `{provider: 'langgenius/openai_api_compatible/openai_api_compatible', name: 'deepseek-chat'}`，system prompt 注入 `top_issue={{#parse-report.top_issue#}}，Top3打穿率={{#parse-report.coverage#}}%`
- 两个 end 节点 outputs 补 coverage 变量
- **断言自检**：所有新边 source/target、analyze/gen/eval/video 四 http 节点 timeout=dict、llm name=deepseek-chat、check-rate 两条件

产物：`dify/workflow_v2.yml`。commit+push（`feat: 工作流v2——analyze前置+mode+coverage分支+DeepSeek容灾(程序化构建)`）。

**注意 analyze 时长**：full=false 跳过 L2/L6，剩 L1+L7+L8 约 3-5 次 DeepSeek 调用，实测 60-120s，http read timeout 3600s 足够。

---

### Task 7: Dify 加 DeepSeek 官方凭据（P2-1 容灾）

**Objective:** 「否」分支脱离 yunwu 单点。

**前置: admin 密码未知（实测 admin@test.com 登录失败）。** 用 Dify 自带 CLI 重置（本地实例合理操作）：

```bash
docker exec -it docker-api-1 flask reset-password
# 交互输入邮箱 admin@test.com + 新密码（记入 macOS keychain: security add-generic-password -a dify -s dify-admin -w <新密码>）
```

（terminal pty=true 跑交互。若用户反对重置，改为用户提供密码/自己登录，后续步骤相同。）

**登录拿 console_token：** 浏览器开 http://127.0.0.1 登录 → console 执行 `JSON.parse(localStorage.getItem('console_token'))` 或直接 `localStorage.getItem('console_token')`。

**加凭据（console API，字段以实际抓包/文档为准，失败则退回 UI 手动添加——一步操作）：**

```javascript
await fetch('/console/api/workspaces/current/model-providers/langgenius/openai_api_compatible/openai_api_compatible/models/credentials', {
  method:'POST', headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},
  body: JSON.stringify({model:'deepseek-chat', credentials:{
    api_key:'<.env 里 ANALYZER_API_KEY 的值，原样>',   // DeepSeek 官方直连，不走代理
    endpoint_url:'https://api.deepseek.com/v1',        // 只到 /v1，插件自动拼路径
    mode:'chat', context_size:'64', max_tokens:'8192', function_calling:'not_support',
    vision_support:'not_support', stream_mode:'default', tokenizer:'',
    endpoint_url_type:'external'}})})
```

**验证:** 模型列表出现 deepseek-chat；注意端点直连中国可达，容器 HTTP_PROXY 也能走（NO_PROXY 不影响外网域名）。

---

### Task 8: v2 导入、发布、切换触发器（P1-1 收口）

**Step 1: console API 导入 v2**（免文件上传坑）：

```javascript
await fetch('/console/api/apps/imports', {method:'POST',
  headers:{'Authorization':'Bearer '+token,'Content-Type':'application/json'},
  body: JSON.stringify({mode:'yaml-content', yaml: <workflow_v2.yml 全文> })})
```

（若 imports 接口字段不符，退回 serve_dsl.py + 浏览器文件上传方案——skill 已验证可行。）

**Step 2: 发布** `POST /console/api/apps/{new_app_id}/workflows/publish`
**Step 3: v2 应用建 API key** `POST /console/api/apps/{new_app_id}/api-keys` → 替换 .env 的 DIFY_API_KEY（echo 覆盖该行）
**Step 4: 真跑 v2 红路验证**（此时配额未恢复，预期行为是 gen 节点 502 → 整条 failed——这正是 Task 3 的语义验收）：

```bash
curl -s -X POST http://127.0.0.1/v1/workflows/run -H "Authorization: Bearer $DIFY_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"product_id":"P001","gen_limit":1,"mode":"styles"},"response_mode":"blocking","user":"v2-audit"}'
# 期望: status=failed，error 含 502/insufficient_quota —— 错误如实上抛 = 修复生效
```

**Step 5:** node_executions 应见 analyze→gen(失败) 前后有序执行。commit 状态记录进 docs。

---

### Task 9: 清理死壳 app + /report 归位（P3）

**Step 1:** console API 删两个死壳：
```javascript
for (const id of ['6d432fa3-9875-45b9-8cff-9aa2b9ecd226','a7033fe9-092f-47e1-bd04-9a01c70d0aed'])
  await fetch('/console/api/apps/'+id, {method:'DELETE', headers:{'Authorization':'Bearer '+token}});
```
（DB 确认两 id 均 0 workflow，删除安全；保留 v1 app 0851b74d 作为对照或一并删除由 v2 完全替代——默认保留，UI 改名加「v1-旧」后缀。）

**Step 2:** /report 端点写进 README「调试用途」说明（保留，不删）。

---

### Task 10: 闭环验证（红路今天跑，绿路设门禁）

**红路 E2E（配额耗尽下即可全部完成）：**
1. `pytest tests/ -q` 全绿（≥120）
2. v2 run → failed at gen + 502 透传（Task 8 Step 4 已证）
3. `launchctl kickstart` → 日志有 trigger、DB 有新 run 行（Task 2 验收）
4. 仓库 clone 到 /tmp 重导 workflow_v2.yml → Run Steps=7（证明仓库版自包含可用）
5. 旧 key 调 /v1/info → 401（Task 1 验收）

**绿路门禁（等 yunwu 配额恢复后自动/手动触发）：**
```bash
# 配额探针：返回无 insufficient_quota 即恢复
curl -s -x http://127.0.0.1:7897 https://yunwu.ai/v1/models -H "Authorization: Bearer $(grep ARK_API_KEY .env | cut -d= -f2)" | head -c 200
# 绿路 E2E: v2 run P001 mode=styles limit=1 → succeeded + P001.mp4 更新 + coverage 数值入 outputs
# 换 mode=screens 再跑一轮 → 八屏图 + Top3 打穿率显著高于 styles（方法论闭环的最终实证）
```

**文档收尾:** DIFY_SETUP_TUTORIAL.md 增补 v2 节点说明与红路/绿路验收表；README 更新架构图说明。全部 commit+push。

---

## 执行时序与用户配合点

| 任务 | 需用户配合？ | 说明 |
|------|------------|------|
| T1-T6, T9-T10 | 否 | 全自动（T1 历史清除可选确认） |
| T7 | 重置 admin 密码需确认（或提供现有密码） | 一次性 |
| T10 绿路 | 需 yunwu 配额恢复（充值） | 红路不受阻 |

## 风险与回滚

- **T1 轮换后 cron 断连**: 新 key 先入库验证再改脚本，顺序保证无空窗。
- **T3 502 语义变更**: 已发布 v1 工作流对失败更敏感——本就是目的；v1 保留可随时切回。
- **T6 v2 导入失败**: v1 app 不动，v2 是独立 app，删了重来零风险。
- **T2 双方案**: 包装器被拦则退部署副本，plist 指向可随时改回。
