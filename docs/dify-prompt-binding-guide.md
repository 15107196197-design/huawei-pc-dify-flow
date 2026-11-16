# Dify 系统提示词绑定与核验

版本1.5，2026-10-19。`prompts/`有10份专用节点System及1份`agent-system.md`完整业务规范；专用节点文件完整复制到对应System即可，完整业务规范不是现有JSON节点的替换文件。不需要模型读取磁盘文件，也不依赖Dify不存在的include语法。工作流生成器读取同一文件并保存SHA256，避免文档版与运行版分叉。源码是可用提示词，模型效果仍待真实测试。

## 节点绑定

| 节点 | System文件 | 主要输出 |
| --- | --- | --- |
| scene_parse | ../prompts/scene-parse-system.md | 意图/缺口，不补产品事实 |
| product_intro | ../prompts/product-intro-system.md | 最短链有据产品介绍 |
| platform_strategy | ../prompts/platform-strategy-system.md | 人群任务、切入点、卖点顺序、图意、CTA策略 |
| article_write | ../prompts/article-system.md | 公众号/小红书/朋友圈ContentDraft |
| poster_copy | ../prompts/poster-system.md | 独立单张海报文案，1主视觉/≤3卖点 |
| visual_layout | ../prompts/layout-system.md | 已核验文案和原图的布局计划 |
| fact_compliance_review | ../prompts/review-system.md | 全文事实/价格/合规及场景平台适配finding |
| visual_review | ../prompts/visual-review-system.md | 对实际图片输入的可见问题，不证明来源 |
| quote_explain | ../prompts/quote-explain-system.md | 只解释已复算且获准的CustomerQuoteSummary |
| sales_demo | ../prompts/sales-demo-system.md | 六段180秒逐字台词/动作/现场条件分支 |

## 输入放在哪里

System只放静态提示词。User消息用变量选择器绑定前序Code/Template节点输出的`task_bundle_json`，不要把知识库原文拼成System。具体DSL选择器必须引用真实节点ID；不能把本文变量名直接当作已存在节点。

任务包统一键：trusted_context、task、evidence、allowed_assets、policy、strategy_plan、quote_context、draft、validator_feedback。任务意图可由用户提出；trusted_context/evidence/资产/授权全部从受认证服务重建，丢弃用户伪造的同名字段。不存在/未核验字段保留缺口，不以模型填空。scene_parse单独接原始输入和已确认意图。

输出固定JSON；代码严格解析并拒绝坏JSON、未知状态和伪造ID。ContentDraft按既有合同，所有claims.target和审核coverage.checked_target_refs用RFC6901 JSON Pointer，如/content/blocks/0/text。产品/业务主张引用fact_ids/business_rule_ids；报价主张用quote_binding={quote_ref,quote_version}绑定客户摘要，不能引用内部P4充数。审核还必须主动检查claims未登记的实际文本。

## 生成与硬门禁分工

提示词约束表达，程序控制真实鉴权、目录回退、原文取证、来源模式、图片身份/数量、精确求价/独立复算、授权、版本、渲染、导出。ready只是候选。审核模型不能签发VALID_OPTIMAL或export_allowed。

含价任务只有当前有效且独立复算的VALID_OPTIMAL、对应SKU/版本、当前用途/模型获准摘要才可生成金额；无报价任务无需等待P4。当前v7的规则不足，真实金额分支保持阻断。布局/视觉只用必要的已核验文字/图，不为排版索取全量报价。

最短产品介绍链只证明产品介绍、模型协作和代码门禁，不能称四平台/海报/报价/销售稿已完成。纯报价和纯销售脚本可无content_channel；含营销输出才要求公众号/小红书/朋友圈/海报渠道。

## 八模块与实质适配验收

article/poster两份完整覆盖手册四（三）的角色任务、场景理解、平台规则、知识库约束、图片规则、生成要求、核验规则、合规规则；专用节点按分工补充，不要求布局节点代写文章。

同型号对照：学生/家长先课程软件门槛与作业链；差旅先离线连接会议；创作者先具体素材和导出；家庭先迁移账号外设；企业先岗位依赖和IT/服务；到店聚焦一个可核动作；首发有可比前代证据才写变化；节日先收礼人任务，有依据才写活动。

不是要求八段固定文案，而是每次从任务选择有据点。更换场景要改切入、卖点顺序、动作和图意；更换平台要改结构、语气、有效图数及CTA，并比较前后策略。公众号2–4、小红书3–6、朋友圈1–3、海报1主视觉/≤3卖点；素材不足阻断，不复制或生成图凑数。海报具体1图规则优先，不能为数量变化造第二图。

先做静态合同/来源检查，再跑真实模型对照样本，再验真实图片/PNG/导出/重新打开。完整测试规格见acceptance-cases.csv；未运行不得把规格条目算成绩。节点失败或修改后须重查当前版本，不能让写手直连Answer绕门禁。

## 正式成品补充：四级组合与最低现金购买方案

用户已要求正式输出包含四级组合比对后的最优购买方案，并随目标人群/场景/渠道调整话术。默认complete_package的marketing及所有full_package要求quote_required=true、purchase_plan_required=true；用户明确选择marketing/content_only时两项为false，仍执行图文完整核验。单纯product_intro只用于显式介绍或开发分支，不作为完整交付。缺规则/资格/有效计划时不能用无报价稿冒充任务完成。

方案服务生成同SKU合法组合对照及适配SKU可比覆盖，解释每级适用/不适用/互斥、依据、现金与资源消耗、条件和有效期。customer_payable_minor语义为同一已核验权益和旧机条件下本次现金，完整商品应付与抵付另列；不重复减回收款，不计未来返分。平台正文用合适话术讲关键理由，完整获准对比表/卡随稿交付；四部分最终呈现仍保留。所有数值由服务格式化，LLM不计算或签发最优状态。

## 2026-10-19实际绑定与模型运行

主应用[b9f0ecf9](http://localhost:8080/apps)共112节点，37个Code和14个LLM System已与当前源码及最新导入包逐字哈希核对。article/poster为3.2，platform_strategy为1.5；visual_review完整提示词尚未作为主流程的真实视觉节点接入。`agent-system.md`只是总业务规范/另行配置单Agent的候选，不在当前主流程中冒充实际System。

[平台策略阶段联调](http://localhost:8080/apps)已实际调用DeepSeek Flash读取本地事实。1.5复测返回blocked_evidence，明确ima与图片缺口，仅显示开发策略；不表示完整营销通过。全链授权与单阶段授权分别保留，阶段许可不能扩展为正文、视觉或成品导出许可。
