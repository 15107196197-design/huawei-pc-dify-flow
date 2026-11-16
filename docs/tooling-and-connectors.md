# 开发技能与连接器记录

> v1.4当前执行基线：用户已授权继续本机Dify安装及业务搭建、修订提示词和准备参赛提交材料；先前“仅交文档”的范围已被后续指令扩展。知识来源采用用户确认的本地v7开发＋参赛ima实时/关联核验双模式，详见[知识源模式](knowledge-source-modes.md)。节点System与变量绑定以[提示词绑定指南](dify-prompt-binding-guide.md)、[提示词登记](../specs/prompt-registry.json)为准。不能用本地读取冒充API达标；实现、离线测试、平台导入、真实运行和参赛验收分别记录。

版本 v1.3　核验日期 2026 年 10 月 18 日

本记录区分Codex开发环境、平台原生节点和业务运行服务。基线为 **用户本机Mac自部署Dify Chatflow + 小型工具服务（ima/quote/render/auth）**，Coze为资格核实后的替代。技能安装、文档阅读、客户端可读库、API连通、画布运行和DSL复测分别留证，不能互相替代。

## 已安装的Codex技能

| 技能 | 来源 | 本机状态与用途 |
| --- | --- | --- |
| ima-skill 1.1.10 | [腾讯官方包](https://app-dl.ima.qq.com/skills/ima-skills-1.1.10.zip)，手册p6指定 | 完整目录已安装，已审查脚本/知识库模块/API合同，Node语法检查通过；项目调用仅只读 |
| playwright | [OpenAI官方仓库](https://github.com/openai/skills/tree/main/skills/.curated/playwright) | 已安装，供真实浏览器流程验证；CLI/浏览器/依赖待开发时核验 |
| security-best-practices | [OpenAI官方仓库](https://github.com/openai/skills/tree/main/skills/.curated/security-best-practices) | 已安装，后续安全默认实现/明确审查使用；未对尚不存在的应用签发安全通过 |
| security-threat-model | [OpenAI官方仓库](https://github.com/openai/skills/tree/main/skills/.curated/security-threat-model) | 已安装，供后续仓库威胁建模，不自动增加审批流程 |
| gh-fix-ci | [OpenAI官方仓库](https://github.com/openai/skills/tree/main/skills/.curated/gh-fix-ci) | 已安装，供未来真实GitHub Actions排障；当前无CI执行证据 |

路径在本机 `~/.codex/skills/` 对应目录，完整性记录为 `research/skill-installation-manifest.json`。本次ima ZIP SHA256：

```text
7e0d07cae0f98145dc5147e84b77bcc557e2fc4b256b08907922637952c20a7b
```

哈希不是官方签名或最新版本证明。其余技能通过skill-installer从官方curated目录安装，未编造版本号。既有PDF技能用于完整阅读手册及9页视觉核验，插件管理用于选择连接能力。

这些是Codex开发技能，**不是已经安装在Dify/Coze的节点**。本机imagegen、浏览器、登录态和文件权限不自动成为应用运行能力；自部署Dify的Code仍在独立sandbox中，不能将Mac主机Skill目录和Shell当原生节点能力。线上服务受控部署官方依赖，不硬编码开发者主目录。

## 连接器和平台状态

| 能力 | 当前证据 | 对交付的意义 |
| --- | --- | --- |
| GitHub | 此前目录返回installed=true、ENABLED | 已有连接器；未新建仓库/提交/PR，不等于验证目标仓库写权 |
| ima Codex连接器 | ima/Tencent/腾讯目录查询未返回匹配 | 用官方Skill/OpenAPI；没装第三方MCP，不能断言全球不存在ima连接器 |
| Dify / Coze Codex连接器 | 本次相关目录查询未返回匹配 | 不等于平台不能用；采用平台原生Provider/HTTP/Tool，未安装第三方画布/转换插件 |
| 本机Mac自部署Dify | 用户已选定本机部署，执行进行中；节点/Provider等官方资料已核验 | 本记录不先认定容器/页面启动或安装完成；具体版本、启动/健康检查与画布结果由实际记录补充，尚无已验收业务画布/DSL复测/付费模型结果 |
| Coze条件候选 | 中国旧低代码官方资料已核验，国际动态正文提取有限 | 先核旧低代码账号资格/套餐；中国、国际、新扣子编程、Studio分开，未部署Studio |
| 小型业务工具服务 | 目前只有接口合同和实施规格 | ima只读、确定性报价、PNG/下载、身份授权；不默认另建完整Web或模型管理后台 |
| 模型/图像服务 | 已读部分官方能力文档，未配置真实应用连接 | 未付费调用，无质量、时延、额度或费用实测通过 |
| 魔搭展示/托管 | 已纳入比赛交付，尚未部署 | Dify/Coze发布不自动满足魔搭展示；账号/网络/评审访问和资料许可另核 |

目录结果非全球完整清单。以后确有缺失的连接能力再按具体权限补充，不为清单完整安装Notion、Linear、Figma或第三方ima MCP。

## ima取证与价格资料

共享网页无登录读取没取得正文；随后主任务通过用户已登录的 **ima原生客户端**阅读指定库的部分建库规范、产品/图片索引、平台和场景材料，并补读P4合规检查/渠道报价/建议零售价三份。客户端可读不等于应用OpenAPI连通，也不等于已读全库或核验全部原图。

四级名称已由用户确认，来源为 **user_confirmed**：基准价 / 平台优惠 / 身份权益 / 换新国补。清单不是执行顺序，也不说明优惠全享或可叠加。已读P4三份仍为 **v0.1空模板**，真实规则、顺序、资格和可执行数字待ima来源核验。当前报价和脚本交确定性合同、内部绑定模板和安全待核验话术，不能造优惠或宣称已得到真实最优报价/可照读金额稿。

用户确认加入指定库且持同账号OpenAPI凭证；此前本机只检查环境变量/配置存在性，未检测到已配置，未读取/记录秘密。**应用运行环境鉴权API读取仍未验证**。以后由工具服务查精确目标库、分页/空搜索目录回退、读授权原文和图片并留脱敏样例；客户端截图不当API运行证据。

官方包是CLI/OpenAPI技能，不是已接通的官方MCP。每日更新检查、两层错误、缺显式请求超时、Base URL可覆盖等须受控包装；锁官方origin/只读接口，添加超时、脱敏与源权限。ima研究（本机工作底稿）的早期时点记录不应覆盖后续客户端取证事实。

## 平台实施方式

默认在用户本机Mac自部署Dify，再建立Chatflow；部署执行中，实际结果待记录。业务主链跑通追问、资料读取、内容/报价/脚本分流、版本审核、PNG和Answer。模型在Integrations→Model Provider配置，LLM节点绑定实际型号和提示词；Code只做JSON/条件检查，外部工作走固定HTTP/Tool。复杂路由/硬任务预算/特殊图像协议才按需扩展小型服务。

先按场景和必要约束筛选一个或多个适配SKU，逐SKU求最低实付、有据比较，让对客稿讲清推荐理由及最终选定SKU报价；不把最便宜当适配，不混SKU事实/价格。连接/档案/路线/提示词/产物版本用平台配置与清单记录，不全部另建页面/数据库。首版同任务至少2种真实模型，可同供应商，不强制购买2家/4种服务。保留模型合同不等于重造通用模型网关、六标签管理页或全套配置CRUD。

本机自部署不表示云模型也在本机，外发授权仍逐目的/供应商/地域核验。workspace是协作域，不是门店业务租户，API user也非平台认证身份。Key共享、日志可见、发布入口和工具服务资源授权分别验证。[Dify Provider](https://docs.dify.ai/en/self-host/use-dify/workspace/model-providers)、[End User Identity](https://docs.dify.ai/en/api-reference/guides/end-user-identity)

中国Coze旧低代码不再向新注册账号开放，自定义模型/导出有套餐权限；不能保证新账号照旧教程一键搭建。国际版HTTP/导出/渠道单独核验，不照搬中国规格。不自动安装官方开源仓库，不用第三方转换DSL代替目标实例复验。[Coze使用说明](https://docs.coze.cn/guides_use_workflow)、[FAQ](https://docs.coze.cn/guides_FAQ)

## 运行提示词、报价与海报

[多模型设计](multi-model-design.md)和平台策略/图文/海报/布局/文字与视觉审核提示词，以及quote_explain/sales_demo，是待映射到节点的业务规格，不是已实现的技能加载器或新连接器。换模型与换业务规则分别版本化。

报价服务对每个适配SKU验证销售约束并分别求最低实付，比较并选定后提供最终SKU冻结的customer_quote_ref顾客摘要。quote_explain和sales_demo不算价、不换方案、不接收内部底价/成本/返利/审批。报价变化使旧解释和脚本失效。[三分钟设计](sales-demo-script-design.md)及[提示词](../prompts/sales-demo-system.md)当前未真实绑定，未做店员实演计时。

PNG服务保持ima产品原图层并叠加可编辑文字。专用图像模型只是获准草案/背景的条件能力；配置Provider不等于比赛允许生成图或外传库内素材，本机imagegen也不直接当业务接口。来源/型号/文字/比例/真实PNG须平台链路验收。

## 待实施交付

形成目标实例版本/套餐和节点清单、逐节点配置/变量表、prompt/Schema、模型绑定清单、服务OpenAPI与测试、脱敏环境变量说明、端到端证据。部署与画布构建逐项记录，真实搭建后才导出DSL，检查Secret/依赖后干净导入复测。用户补足空间后当前部署正在续拉官方镜像，未登记已验收业务画布、可用DSL或付费结果；部署完成与业务完成分开核验，配置样例不冒称成品。

依据详见Dify研究（本机工作底稿）、Coze研究（本机工作底稿）和图像研究（本机工作底稿）。账号功能/外部权限/资料许可未验证项保留为实施门槛，已授权的规格、工具代码和测试准备可继续推进。

## 本次本机部署实际结果

Dify1.17.1官方源码已取得，Lima2.2.1官方SHA256已核验，Linux guest与Docker29.9.1 rootless/Compose5.6.0已成功运行，Compose配置检查通过。当前镜像下载/解包触发5GiB磁盘保留线（最低约4.59GiB），先前任务VM已正常关闭，用户补足空间后现已重启续装，平台部署尚未完成。源码、配置和VM状态保留，目标HTTP/管理员初始化未验收。详见 [部署状态](dify-local-deployment.md)。本机4GiB guest是单用户试运行，低于官方Mac8GiB VM指导；不能据此声称正式并发通过。
