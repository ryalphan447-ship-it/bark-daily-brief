# 每日 Bark 新闻简报

每天北京时间 **09:00 触发** GitHub Actions，读取免费公开 RSS，生成适配 iPhone 的 HTML 简报，发布到 GitHub Pages 后发送 Bark 通知。点击通知打开完整简报；新闻全文通过原文链接阅读。

Python 3.12 标准库实现，不需要安装第三方 Python 包，不需要 OpenAI API Key、服务器或付费域名。首版是 RSS 摘要汇总，不是 AI 深度分析，不会自动读取或转发 ChatGPT 对话。

## 上线步骤

1. 创建公开仓库 `bark-daily-brief`。把本项目内容上传到仓库根目录，默认分支通常为 `main`。必须保留 `.github/workflows/daily.yml`，不要把整个项目再套一层目录，也不要只上传 ZIP。
2. 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。若看到必须付费，检查仓库是否是 Public；免费账户的私有仓库不适用于本教程的 Pages 方案。
3. 仓库 **Settings → Secrets and variables → Actions → New repository secret**：
   - Name：`BARK_KEY`
   - Secret：你在 Bark App 中对应 `api.day.app` 服务器的设备密钥。
   - 如果 App 给出完整测试链接，只取域名后第一个路径段作为密钥，不要填写整个链接。
   - **由你亲自粘贴并保存，不要发到聊天、截图、Issue 或代码文件。** 不要添加到 Variables。
4. 打开仓库 **Actions → Daily Bark Brief → Run workflow**。选择默认分支，保留“发布成功后发送 Bark 通知”勾选，点击运行。
5. 等待运行完成。确认网页可打开、iPhone 收到通知、点击后看到相同日期的简报，才算端到端验收完成。Bark API 接受请求不等于 iPhone 已展示通知。
6. 之后无需保持电脑开机，GitHub 云端负责运行。不要重复创建 ChatGPT 定时任务。

首次仅测试网页时，可取消手动运行中的通知勾选。公开仓库不要邀请不可信协作者；可以修改工作流的人可能使运行时 Secrets 泄露。

## 默认行为

- 来源：联合国新闻中文、BBC 中文、IT之家。公开 RSS 不需要 API 密钥。来源覆盖有限，并非全面新闻榜单，可自行在 `config.json` 替换。
- 回看最近 24 小时，每来源最多 4 条，总计最多 12 条。按发布时间排序；同链接（忽略常见跟踪参数）或相同标题去重，不做语义事件合并。
- 摘要取自 RSS，最多 120 字符；没有摘要时显示原文入口，不编造摘要。日期不明的条目跳过，页面披露跳过数量。
- 单个来源失败重试一次；部分失败仍发布但标注覆盖不完整；全部失败则停止发布和推送。有效来源没有新条目时发布“暂无新条目”，不会拿旧内容凑数。
- 先发布页面，再核对页面内本次运行的标识，确认访问到新页面才发送通知。
- **网址只保留最近一期。旧通知点击后也会打开最近一期，不是历史存档。** 这样无需数据库、归档分支和长期存储；后续可独立加入归档功能。
- Bark 通知只包含日期、标题、条数和阅读链接，不在锁屏上显示新闻细节。使用 JSON POST `/push`，密钥放在请求体，不放在 URL。异常日志不输出请求、响应正文或密钥。
- Bark POST 超时不自动重试，防止重复通知。手动重新运行会重新发布，并可能再发一条；首版没有跨运行的“恰好一次”保证。

## 时间与维护

`.github/workflows/daily.yml` 的 `0 1 * * *` 是 UTC 01:00，即北京时间 09:00。**这是触发时间，不是保证送达时间**；排队、抓取、部署会再花时间，GitHub 也可能延迟甚至丢弃高峰期调度。如果接受 09:07 左右触发，可改为 `7 1 * * *` 避开整点，但仍无准点保证。

定时运行仅使用默认分支。公开仓库连续 60 天无活动时，GitHub 可能自动停用定时工作流；本项目不通过无意义提交保活。建议每月检查一次 Actions、更新新闻源或维护代码。被停用时在工作流页面重新启用，并手动测试一次。开启 GitHub Actions 失败通知；整个工作流未被调度时，系统自身无法发送故障提示。

## 成本与隐私

在 GitHub Free 的公开仓库、标准 `ubuntu-latest` 执行器、GitHub Pages 默认域名及免费 RSS 的组合下，设计目标是 **0 元/月**，无付费 AI 调用。使用限制和免费政策以平台当前规定为准；不要选择付费大型执行器。Pages 上传产物保留 1 天，页面很小；未使用长期缓存。失败日志仍按 GitHub 保留设置保存。

**公开仓库和 Pages 网页任何人都可能访问。** `robots.txt` 和 `noindex` 只是请求搜索引擎不要收录，不能阻止访问、转发、截图或第三方缓存；随机链接也不等于访问控制。不要在配置、网页、代码、Actions 日志或产物中加入姓名、住址、资金余额、个人持仓、健康资料、餐食过敏信息等私人内容。把源代码仓库改成私有，也不应据此认为 Pages 自动成为私密网站。

GitHub 存储 Secrets 并在运行时提供给代码；它们不是对仓库维护者或恶意工作流的隔离。请求通过 HTTPS 发给 Bark 公共服务，再经 Apple 推送。当前版本未启用 Bark 的额外端到端内容加密，相关服务会处理通知内容和链接；HTML 网页本身是公开的。密钥泄露后应在 Bark 重置，再更新 Secret。GitHub Pages 会因安全目的记录访问 IP。不同地区的网络可能影响 Pages、RSS 或原文访问，需要用 iPhone 实测。

RSS 免费可访问不代表允许无限转载。只做个人阅读导航，保留来源、短摘录和原文链接，不抓取新闻全文；公开分享或商业使用前核对各来源条款。

## 与现有 ChatGPT 定时任务的关系

这是一套独立的云端任务。**不能把现有 ChatGPT 定时任务直接转发到 Bark**：没有在本项目中可直接配置的现成 Bark 转发接口，现有任务内容也不会自动同步。官方文档介绍了 ChatGPT 定时任务和连接工具的能力，但未提供本方案所需的现成“任务结果 → Bark”配置。若以后要使用模型生成分析，需独立设计数据收集和 API 调用，并另行核算费用，不能把 ChatGPT 订阅当成免费 API 额度。

## 本地测试（可选）

```text
python -m unittest discover -s tests -v
python brief.py build --demo
python brief.py build
```

第一条是无需网络和真实密钥的自动测试；第二条生成明确标为演示的网页，禁止推送；第三条才抓取真实来源。打开 `site/index.html` 查看。不要在命令中直接写密钥，也不要提交 `site/`、`work/` 或 `.env`。

## 排错

| 现象 | 处理 |
| --- | --- |
| Actions 没有这个工作流 | 检查 `.github/workflows/daily.yml` 是否位于默认分支的准确路径 |
| Pages 配置失败或 404 | Settings → Pages 的 Source 选 GitHub Actions；查看部署步骤状态 |
| 等待环境审批 | 由仓库所有者审核并批准当前部署；不要删除组织要求的保护规则 |
| 缺少或无效 BARK_KEY | 核对 Repository secret 名称和设备密钥；不是 Variable，也不是整段 URL |
| 全部 RSS 失败 | 稍后手动重跑；在 `config.json` 更换 HTTPS RSS，检查源是否停止服务 |
| 有页面但不推送 | 检查本次是否取消通知选项、Pages 可访问性、Bark 步骤结果 |
| Bark 接受但手机没有显示 | 检查 iOS 通知权限、专注模式、联网状态以及 App 所用服务器；不要发送密钥排错 |
| 推送重复 | 手动重跑或请求超时可能重复；先查看手机再决定是否重新运行 |
| 09:00 尚未收到 | 看 Actions 是否排队；GitHub 调度不保证准时 |
| 两个月后不再自动跑 | 检查定时工作流是否因仓库不活跃而停用 |

## 后续扩展路线（尚未实现）

| 模块 | 低成本实现方向 | 上线前需明确 |
| --- | --- | --- |
| 股票 | 接入允许使用的行情接口和交易所公告，展示数据时间和延迟 | 市场、标的、交易日、接口许可；不在公开网页放个人持仓 |
| 投资 | 使用公开报告/公告形成阅读清单，标出处和日期 | 不自动交易，不把信息摘要当成个性化投资建议 |
| AI 工具 | 在配置中加入厂商官方博客 RSS，按关键词筛选 | 首先核验功能与价格来源；无 RSS 时另写抓取适配 |
| 餐食 | 可先用本地通用食谱表轮换，无需模型费用 | 个性化忌口、健康情况等必须使用受访问控制的存储和页面 |

这些模块应复用“收集 → 规范化 → 渲染 → 发布 → 推送”的流程。公开数据类先接入；需要个性化资料时，先迁移到带身份验证的托管页面，再增加功能。当前项目没有登录系统，也不隐藏任何已发布内容。

## 官方参考

- [GitHub Actions 定时触发、延迟与停用规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Actions 计费](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Pages 可用范围与隐私说明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [GitHub Pages 工作流](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Bark 官方推送文档](https://github.com/Finb/Bark/blob/master/docs/en-us/tutorial.md)
- [ChatGPT 定时任务](https://learn.chatgpt.com/docs/automations)

配置规则与参考文档核对日期：2026-10-21。
