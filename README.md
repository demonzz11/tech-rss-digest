# 科技 RSS → AI 摘要 → 微信推送

Python + GitHub Actions + AI API + PushPlus。无需自己的服务器，无需数据库。
当前配置使用本机 CC Switch 同一服务的 `gpt-6.1-sol` 模型，通过 Responses API 生成摘要；也支持 Chat Completions API 及 DeepSeek 官方服务。

| 报告 | 默认发送时间（北京时间） | 内容范围 |
| --- | --- | --- |
| 日报 | 每天 08:00 | 实际运行前 24 小时的新文章 |
| 周报 | 每周一 09:00 | 上周一 00:00 至本周一 00:00 |
| 月报 | 每月 1 日 10:00 | 上月 1 日 00:00 至本月 1 日 00:00 |

日报/周报/月报都调用配置的 AI 模型生成中文摘要，附原文链接，通过 PushPlus 推送。
英文 RSS 也用中文总结；摘要仅依据 RSS 标题和摘录，不抓取文章全文。

## 1. 上传至 GitHub

创建 GitHub 仓库，将本项目文件上传至默认分支，例如 `main`。必须包含隐藏目录 `.github/workflows/`。
不要上传本地 `.venv/`、`archive/`、`output/` 或任何包含真实 Token 的文件。

仓库内需要的文件：

```text
.github/workflows/rss-reports.yml
rss_digest.py
config.json
requirements.txt
tests/test_rss_digest.py
.gitignore
.env.example
README.md
```

## 2. 配置两个 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions → New repository secret**：

| Secret 名称 | 填写内容 |
| --- | --- |
| `DEEPSEEK_API_KEY` | 当前 AI 服务的 API Key（保留原 Secret 名称，第三方服务也使用此项） |
| `PUSHPLUS_TOKEN` | 你的 PushPlus Token |

不要把实际 Token 填入 `config.json`、工作流文件或 Git 提交。`.env.example` 只有占位符；脚本不会自动读取 `.env`。
如果 Token 已公开或粘贴进聊天，建议在服务控制台更换，再配置新 Token。

在 PushPlus 控制台按提示绑定接收消息的微信，并确保 AI 服务账户可以调用配置的模型。

## 3. 首次运行

1. 仓库 **Actions** 中启用工作流（如果是 fork，先允许该仓库运行 Actions）。
2. 打开 **科技 RSS 日报 / 周报 / 月报 → Run workflow**。
3. 选择 `daily`，点击运行。
4. 查看日志及微信消息。报告 HTML 会保存在该次运行的 **Artifacts** 中，保留 30 天。

工作流已声明 `contents: write`，会自动建立 `rss-data` 分支保存数据。若组织策略或分支规则拒绝写入，需要允许本工作流向该分支推送。
定时工作流文件必须位于默认分支。之后无需手动运行，也无需让本地电脑保持开机。

## 数据怎样保留

Actions 临时机器在运行结束后消失，所以历史数据写入仓库的独立 `rss-data` 分支：

```text
articles/2026-10-03.json            # 按文章发布时间归档的 RSS 数据
reports/daily/2026-10-03.json       # 摘要和 PushPlus 接收记录
reports/weekly/2026-09-21_2026-09-27.json
reports/monthly/2026-09.json
```

每次运行补采 RSS 中仍可取得的最近 35 天条目；日常存档保留 120 天的文章文件。
周报和月报从这些 JSON 中筛选上周/上月文章，再交给 AI 总结，无需数据库。
删除旧文件不会清除 Git 历史，仓库仍会随长期运行增长。

首次使用时，RSS 通常无法提供完整的上周或上月历史；启用后的报告会逐渐完整。
漏跑或来源已删掉的历史条目无法保证补回。报告会提示历史覆盖限制。

同一期报告被 PushPlus 接收后，再次运行会跳过。日报还会过滤近三天已推荐过的原文链接。
周报/月报允许再次总结日报中的事件。手动运行时勾选 `force` 可以重发同一期。

## 修改 RSS、条数及时间

编辑 `config.json` 中的 `feeds` 可增删来源，默认包含 IT之家、Solidot、阮一峰的网络日志、TechCrunch、Ars Technica 和 The Verge。
单个源失败时继续使用其他源，报告注明失败来源；全部失败且本期没有存档时任务失败。
不带可解析日期的文章会跳过，避免归入错误月份。按标准化后的原文 URL 去重，跨媒体重复事件由 AI 尽量合并。

`max_articles` 控制交给 AI 的候选条数，`max_highlights` 控制最终要点数量。
日报候选按来源轮流选择，同一来源内优先最新条目；周报/月报先覆盖不同日期，再兼顾当天不同来源，避免只选到月末新闻。月报是精选摘要，不保证覆盖所有事件。
保留天数 `archive_retention_days` 至少为 62。减少候选条数和要点数量通常可以降低 API 消耗。

修改时间需同时修改 `.github/workflows/rss-reports.yml` 中的 `schedule` 和 `case` 匹配项。
cron 使用 UTC，北京时间需要减去 8 小时。`config.json` 的 `timezone` 控制报告日期边界，不会自动修改 cron。

## AI 接口配置

`config.json` 的三个字段控制服务地址、接口格式和模型：

```json
{
  "ai_base_url": "http://47.109.76.66:18001/v1",
  "ai_api_format": "responses",
  "ai_model": "gpt-6.1-sol",
  "ai_headers": {"User-Agent": "codex_cli_rs/0.106.0", "originator": "codex_cli_rs"},
  "ai_max_output_tokens": null
}
```

以上是当前 Sub2API 配置。脚本调用 `/v1/responses`，并从返回结果的消息文本中解析摘要。
Key 必须属于这个服务，保存在 GitHub Secret `DEEPSEEK_API_KEY` 中；无需重命名 Secret。
CC Switch 只负责本机的配置切换。Actions 使用保存在 GitHub Secret 中的 Key 直接访问公网 API，不依赖本机电脑或 CC Switch 程序运行。
当前服务使用 Codex 客户端请求头，并省略 Responses 的可选输出额度参数；这组请求格式已经过实际接口验证。
`ai_headers` 只存放非敏感协议头；API Key 始终从 Secret 读取。其他 Responses 服务可将 `ai_headers` 设为空对象，并按需要设定整数形式的 `ai_max_output_tokens`。

改回 DeepSeek 官方服务时，将三个字段分别设为 `https://api.deepseek.com`、`chat_completions`、`deepseek-chat`，并更新 Secret 为官方 Key。
其他兼容服务使用它自己提供的 Base URL、接口格式与模型名称；不要用第三方 Key 请求官方地址。
平台如支持 `/models`，脚本会在日志中列出当前 Key 可用模型并检查配置。截图中的模型名不一定属于当前 Key 的权限组。
使用可用的 GPT 模型时可将 `ai_api_format` 设为 `responses`。Responses API 的请求与输出解析已包含在脚本中。

## 本地检查

要求 Python 3.12 或更新版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 真实抓取 RSS，检查网络及条目，不调用付费 AI、不推送、不写存档。
.\.venv\Scripts\python.exe rss_digest.py --type daily --dry-run

# 当前 PowerShell 进程中配置环境变量（请自行替换占位符）。
$env:DEEPSEEK_API_KEY = '你的新 API Key'
$env:PUSHPLUS_TOKEN = '你的新 PushPlus Token'

# 调用配置的 AI 服务，生成 output/ 下的 HTML，暂不发送。
.\.venv\Scripts\python.exe rss_digest.py --type daily --no-push

# 真正发送日报；周报/月报改为 weekly / monthly。
.\.venv\Scripts\python.exe rss_digest.py --type daily
```

本地文件不自动同步至 GitHub。周报/月报需有对应时期的本地 `archive/`，或使用 GitHub Actions。

## 运行限制与故障定位

- GitHub 定时任务可能排队、延迟甚至漏跑，特别是整点高峰；08:00 等时间是计划时间，不是送达保证。可修改分钟避开整点。
- 公共仓库长期无活动时，GitHub 可能暂停定时工作流；确认 Actions 中的工作流仍处于启用状态。
- 无需租用服务器，但 AI API、GitHub Actions 私有仓库配额及 PushPlus 服务受各自价格和额度限制。
- `HTTP 401/403`：检查 Secret、API 权限和账户状态；`429`：检查调用额度或频率。
- PushPlus 状态码 `200` 表示服务已接收，实际微信送达仍由 PushPlus 处理。
- AI 请求对临时网络错误、429 和 5xx 最多尝试三次；PushPlus 不自动重试，避免请求超时但已送达时重复发送。
- AI 或推送失败时，工作流仍尝试提交已采集的文章；修复后可重跑。推送成功但保存发送记录失败时，重跑可能重复发送。
- 源站可能屏蔽请求或修改 RSS 地址，查看日志并在 `config.json` 中调整来源。摘要与推送失败不会用伪造摘要顶替。

密钥通过环境变量读取，写入 Git 的内容只有公开 RSS 摘录和生成摘要。第三方 API 的原始错误正文不会进入日志。
