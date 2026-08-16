# 定时任务部署说明（launchd）

## 架构：权威源 + 部署副本

macOS TCC 阻止 launchd 的 bash 读取 `~/Desktop` 下任何文件（状态码 126，"Operation not permitted"）。
因此采用双文件结构：

| 位置 | 角色 | 修改权 |
|------|------|--------|
| `scripts/05_dify_cron.sh` | 权威源（进 git） | 改这里 |
| `~/bin/dify-pipeline/cron.sh` | 部署副本（launchd 实际执行） | 禁手改 |
| `~/bin/dify-pipeline/.env` | 仅含 DIFY_API_KEY（600 权限，不进 git） | 轮换 key 时同步 |

## 改脚本后的同步命令

```bash
cp scripts/05_dify_cron.sh ~/bin/dify-pipeline/cron.sh && chmod +x ~/bin/dify-pipeline/cron.sh
# 若副本中 source 路径被覆盖，恢复为指向 ~/bin/dify-pipeline/.env
sed -i '' 's|^source .*dify-pipeline/.env.*|source /Users/Admin/bin/dify-pipeline/.env|' ~/bin/dify-pipeline/cron.sh
launchctl kickstart -k gui/$(id -u)/com.sunnyworld.dify-pipeline   # 立即触发验证
```

## 排障

- `launchctl list | grep dify` 第二列非 0 → 看 `/tmp/dify-pipeline-cron.log`
- 126 = TCC 拦截（副本不在 ~/bin 或 plist 指错路径）
- `DIFY_API_KEY: unbound variable` = ~/bin/dify-pipeline/.env 缺失或 source 路径漂移
- `status=parse_err` = Dify 未返回 JSON（服务未起或 key 失效）
