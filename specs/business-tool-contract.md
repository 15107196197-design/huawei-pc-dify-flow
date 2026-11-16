# 业务工具唯一逻辑合同

版本 1.4　更新日期 2026-10-18。本文统一节点指南、报价设计与主需求文档中的业务工具路径、字段、状态、权限及版本语义；三份文档应引用本合同，不另造同义接口或状态枚举。

**这是待实现的设计合同，没有已部署服务、已联调 OpenAPI 或真实报价。** 开发 agent 须据此编写严格请求/响应 Schema、OpenAPI、服务端实现及合同测试，再绑定目标 Dify/Coze 节点。示例引用与字段类型不代表真实授权、规则或金额。

已选定默认编排环境为**这台Mac本机自部署Dify Chatflow**，具体部署/联调状态由运行记录确认。本文不包含部署步骤；本机环境不自动授权ima、模型provider、插件等远端调用，也不替代门店隔离、密钥和日志权限管理。

## 1 身份、资料范围与云外发

每个请求先验证服务凭证和可核验的最终用户身份，再解析 tenant/store/actor/role。`tenant_id`、`sys.user_id`、quote_ref及source_context_ref均不能单独当作身份认证；opaque引用也需校验主体、资源、用途、时效和撤权。

源读取与对外披露是两种独立授权：

- `source_access_policy`控制受控服务可读哪些ima资料、能否编译成规则。
- `disclosure_policy`控制哪些白名单字段可送往哪个目的、平台实例、模型供应商/配置及地域。顾客可见不等于可发云平台、云模型或公开内容渠道。

调用方提交的`purpose_ref`和`destination_ref`只作为待校验引用；服务从受控配置解析并验证，不信任LLM自报“已批准”。缺失或不匹配时拒绝相应payload。供应商fallback和模型变更必须重新检查目的/供应商/地域，不能继承更宽权限。

P4默认不进入Dify/Coze云节点、知识库、日志或云模型。**默认云响应只含安全状态、不透明引用和可公开的补充事项**；内部规则、候选全集、applied/rejected规则明细、成本/底价/返利/审批、内部替代方案、最优性证明与原文均留服务端。其他产品事实/图片/品牌信息也只按已批准字段最小交付，不因HTTP成功自动外发。

只有`purpose + destination/provider + region + field allowlist`全部获准，才返回`CustomerQuoteSummary`或相应事实payload。未获准的真实报价留在受控环境，可用本地确定性模板生成客户稿；云端仅收到本地处理引用，不能把私密成稿再上传云端展示。凭证和原文鉴权URL永不进入模型输入。

## 2 唯一端点

`BUSINESS_SERVICE_BASE`是无`/v1`尾缀的已审核服务origin/基础路径；默认对外访问使用HTTPS，本机隔离调试可采用明确审核的本地HTTP地址，不把该例外扩大到未受控网络。下面路径自带`/v1`，节点不能重复拼接。请求目标固定，不接受用户或模型传入任意URL/apiPath。

| 方法与路径 | 请求核心字段 | 返回/责任 |
| --- | --- | --- |
| `POST /v1/contexts/resolve` | 服务认证、最终用户可信证明、task_ref、purpose_ref、destination_ref | 解析受限`source_context_ref`、配置版本、已核准purpose_ref/destination_ref和安全权限状态；不外发机密规则 |
| `POST /v1/kb/evidence` | source_context_ref、product_query/已选product_ref或已确认需求/场景/硬需求、content_channel、sales_platform、所需事实/图片类型、purpose_ref、destination_ref | 服务端ima只读取证/目录回退/冲突，支撑有据适配推荐集；云端默认仅引用和状态，获准事实/图片payload按白名单交付；P4内容和规则留服务端 |
| `POST /v1/quotes/solve` | source_context_ref、product_ref/SKU、quantity、currency、region、sales_platform、as_of、rule_timezone、eligibility_refs、customer_resource_snapshot_ref/version、resource_use_scope_ref、four_levels_spec_ref、price_rule_set_ref、objective、objective_metric/version、task_version_ref、idempotency_key；多SKU比较另绑定recommendation_set_ref | 每次针对一个准确SKU，在同一顾客已核验资源及允许使用范围内精确求本次现金支付最低，保存商品结算、费用、抵付和现金账本/证明；形成可复核候选时返回FEASIBLE_NOT_PROVEN、reason=PENDING_INDEPENDENT_VALIDATION和quote_ref，不返内部明细；独立复算另调用validate |
| `POST /v1/quotes/{quote_ref}/validate` | quote_version、task_version_ref、expected_dependency_hash、purpose_ref、destination_ref | 在冻结资源/允许范围和目标版本下独立回放分层金额/资源消耗，检查销售及资源候选完整/严格现金最优、来源权限/时效；返回validation_ref和结果。缺此步骤不能进入最终报价 |
| `GET /v1/quotes/{quote_ref}/client-view` | 已验证身份；quote_version、purpose_ref、destination_ref（query或受控header） | 重新验权/验期/验用途后按白名单返回CustomerQuoteSummary；未获准则只安全状态与ref |
| `POST /v1/quotes/{quote_ref}/script-input` | quote_version、validation_ref、product_fact_set_ref、customer_need_ref、demo_action_plan_ref、cta_ref、task_version_ref、purpose_ref、destination_ref | 组装脚本允许的最小输入；不获准云端时仅本地处理ref；不能给脚本内部规则 |
| `POST /v1/quotes/{quote_ref}/verify-content` | quote_version、validation_ref、content/script_ref或获准内容、content_hash、task_version_ref、purpose_ref、destination_ref | 比对金额/条件/最优范围/产品引用及保密边界，返回受版本约束检查结果；不让LLM自评解锁 |
| `POST /v1/renders/poster` | 已核验content_ref/hash、LayoutPlan/ref、ima asset_refs、尺寸/模板版本、task_version_ref、purpose_ref、destination_ref | 授权受控排版、真实PNG及渲染/文件哈希；无权外发时不向云平台返回私密图片 |
| `POST /v1/artifacts/finalize` | task/run/version、必需检查refs、content/quote/script/layout/render依赖hash、请求交付用途 | 重确认实际使用来源和报价，原子核对当前本地版本；返回获准manifest/交付引用。无权交付则安全阻断 |

最短产品介绍链可由独立应用credential与最终用户可信证明在kb/evidence服务内部执行同等resolve，再返回source_context_ref；这是已受控绑定的简化方式，不能仅凭应用公开链接或用户自报门店隐式授权。完整链显式先调用contexts/resolve。

源、内部规则与solver接口不暴露为LLM任意可调用工具。最终文件用实际实现的身份授权交付通道获取，每次验证主体/租户/资源；本合同不创造无鉴权公开下载URL。平台目标实现中的文件handler另在OpenAPI列明，不能用对象存储签名直链绕过持续授权。

## 3 包装status与报价quote_status

### 3.1 通信/流程包装

通用响应至少包含`request_id`、`status`、`data`、`error`。`status`只允许：`ready / needs_input / needs_source / conflict / denied / error`。HTTP 200表示请求被处理；`status=ready`仅表示本接口处理完成，**不证明报价最优、资料获准外发或可以导出**。

所有可能含报价的结果另带：`quote_required` Boolean、`quote_status`（下表枚举或null）、`quote_ref`（或null）、`client_quote_allowed` Boolean、`customer_quote_summary`（或null）、`local_delivery_ref`（或null）。`client_quote_allowed`专指**本次请求所声明并经服务核验的目的与目的地**可获取哪些客户字段，不能理解为任意云端都可使用。

任务另保留可信编排策略字段`purchase_plan_required` Boolean；正式marketing/full_package为true，不能由模型改为false绕过成品门禁。方案payload只嵌在customer_quote_summary中，任务字段不是第二份方案。

不报价任务：`quote_required=false, quote_status=null, quote_ref=null, customer_quote_summary=null`。该分支只用于开发验证或用户显式只要产品介绍的`product_intro`；不能把`not_requested`塞进quote_status，也不能因P4待核验阻断该分支产品介绍。**正式`task_kind=marketing/full_package`默认必须`quote_required=true, purchase_plan_required=true`，并含四级组合比对后的获准购买方案，缺报价/方案时只算受阻的部分结果，不得将无价营销稿或产品介绍标为完整交付。**

### 3.2 唯一报价枚举

| quote_status | 意义与后续 |
| --- | --- |
| `BLOCKED_SOURCE_UNVERIFIED` | 四级执行规则未核验，包括当前空模板；名称已确认不代表规则可算，禁止真实金额 |
| `MISSING_INPUT` | SKU/数量/币种/渠道/时点/时区/资格或必要费用信息不足，安全追问 |
| `SOURCE_MISSING` | 必要源不可读或候选不完整，不能当无解 |
| `SOURCE_EXPIRED` | 价格/规则有效期未核实、过期或撤销，重确认来源 |
| `RULE_CONFLICT` | 有效规则冲突或四级语义矛盾，受控核实 |
| `ACCESS_DENIED` | 主体、来源、门店、报价或用途无权，不fallback绕过 |
| `INFEASIBLE_PROVEN` | 完整有效模型证明限定域无可行解，不造报价 |
| `FEASIBLE_NOT_PROVEN` | 有候选但严格最优或完整业务门禁尚未完成，只内部复核；包含solver已证但reason=PENDING_INDEPENDENT_VALIDATION的待复算状态 |
| `VALID_OPTIMAL` | 规则/候选完整、实付确定、硬约束与独立回放通过、严格最优已证；仍须目的授权 |
| `SOLVER_ERROR` | 模型/数值/服务错误，不冒充无解 |
| `CANCELLED` | 取消，不接纳迟到结果为新run成功 |
| `TIMEOUT` | 未完成报价门禁，不能用最后候选宣称最低 |

来源/资格在消费时变化时，由服务重新给出对应不可用状态并使依赖失效；不得继续沿用历史VALID_OPTIMAL。API wrapper、报价状态、solver内部状态和稿件审核状态各自独立，不互相替代。

solve不能在独立validate前给VALID_OPTIMAL。节点09得到quote_ref且quote_status=FEASIBLE_NOT_PROVEN、reason=PENDING_INDEPENDENT_VALIDATION时进入10的validate，而非等待VALID_OPTIMAL；validate重确认solver严格最优、完成独立回放和其他门禁后才提升为VALID_OPTIMAL。若solver本身尚未证明最优，则validate不能只因金额复算一致而提升。client-view随后再独立检查本次用途授权。

### 3.3 当前P4状态映射

用户已确认四级名称为基准价、平台优惠、身份权益、换新国补。名称来源与可执行规则来源分开记录：前者来自用户确认，后者仍须知识库证据。权威状态字段为：

```text
FourLevelsSpec.source_status = pending-source-verification
FourLevelsSpec.name_source = user_confirmed
FourLevelsSpec.rules_source = ima_evidence_required
FourLevelsSpec.semantic_kind = null
FourLevelsSpec.levels = four_named_level_records_with_unverified_rule_refs
FourLevelsSpec.calculation_order_ref = null
FourLevelsSpec.stack_policy_ref = null
real_quote_enabled = false
```

levels的严格结构以 [配置样例](quote-configuration.example.json) 为准：四条level_id/display_name记录已齐，各自rule_refs为空、rule_verification_state=unverified；semantic_kind为null表示执行语义尚未核验。这里不维护独立level_names第二套名称字段。展示顺序不推定为核算顺序。各级金额/比率、计算基数、优惠资格、互斥/叠加、换新与国补的适用关系、核算顺序、舍入、地域及有效期均以知识库证据确定；不能将“换新国补”默认拆成两项必叠加优惠。

`pricing_mode=price4_pending_source`、`pricing_schema_status=price4_pending_source`仅为节点界面的安全投影，当前指已命名、缺执行规则，不是另一套四级定义或报价状态。请求真实报价时映射到`quote_status=BLOCKED_SOURCE_UNVERIFIED`，reason可为`FOUR_LEVELS_PENDING`/`EMPTY_TEMPLATE`；不报价时quote_status仍为null。不能根据名称、文件名或空模板猜公式；不再要求用户重复提供四级名称。

## 4 报价与脚本唯一字段

### 4.1 金额与输入

- `objective`保留`min_customer_payable`；用户已确认其精确定义为`objective_metric=min_cash_due_now_given_verified_customer_resources`、`objective_metric_version=1.0`：使用**同一顾客已核验的权益和旧机条件，在已确认允许使用的资源范围内，让本次现金支付最低**。不暗加利润或渠道偏好，不把资源变多、换另一台旧机或未来积分当作更优方案。
- `cash_due_now_minor`是本次购买在冻结规则与资源下完整结清仍须付的现金；`customer_payable_minor`为兼容字段，必须由服务从`cash_due_now_minor`等值投影，不能独立输入、计算或修改。数学目标为`min cash_due_now_minor`，也即`min customer_payable_minor`。金额为最小货币单位整数，或超平台安全整数范围时的受控整数字符串；不使用`payable_minor`另造歧义字段，不以float传金额。
- `quantity`必须是明确正整数；currency、as_of和rule_timezone需来源/可信业务配置或确认输入。不能静默按一台/人民币/宿主机时区。
- 内部比例、中间结果、舍入与候选完整性按报价设计；未知必计费用不能填0，缺四级顺序/舍入规则必须阻断。

报价金额分层固定如下，服务端精确运算并独立回放：

```text
merchandise_total_minor = 按核验销售规则完成折扣/补贴后的商品结算应付，尚未扣支付工具
order_total_before_payment_minor = merchandise_total_minor + mandatory_fees_minor
cash_due_now_minor = order_total_before_payment_minor - credits_applied_minor
customer_payable_minor = cash_due_now_minor
```

`mandatory_fees_minor`包括未计入商品结算的必计运费/税费/服务费；已包含项不重复加。各金额非负，抵付不得超过对应允许抵付的应付额，运费等不可抵付部分按规则保留。未知金额用null并阻断有效报价，不以0补齐。积分依据核验规则归类为销售减项或支付抵付，只出现一次；无论归类均另记实际消耗点数。回收所得代金券作为支付工具，不能再把同一旧机回收价值当商品优惠扣一次；额外换新补贴、国补另依条款入账。未来返还/购物回馈积分、未质检确定的旧机初估、尚未到账或不可用于本单的券不得列为当前可抵资源。未另行确认分期/订金购买范围时，不通过延后债务制造“本次现金更低”。

`customer_resource_snapshot_ref/version`从可信身份下解析，冻结已核验余额、权益/旧机条件、可用时点、归属、必要有效期及来源证据；`resource_use_scope_ref`冻结顾客允许本次使用的资源集合/上限，不等于实际兑换授权。未知资格/余额若影响现金最优，返回MISSING_INPUT/SOURCE_MISSING等对应状态，不能假定无限或假定为零。不同SKU是同一资源快照上的替代购买方案，不因先算某SKU而减少下一SKU余额；实际多件联合购买须联合约束，不能重复花同一份资源。现金并列的不同资源组合保留获准差异、消耗和余量，不因排序暗选不可逆兑换、回收或支付；本合同所有quote端点只报价，不执行这些动作。条件变化使报价与比较失效。

### 4.2 CustomerQuoteSummary

唯一Schema名为`CustomerQuoteSummary`；`ClientQuote`只是同义名，**不维护独立结构**。`customer_quote_ref = quote_ref`是脚本侧语义别名，值与quote_version必须来自同一报价；不是第二份报价或另一种授权。不得将内部QuoteResult冒充或直接传作客户摘要。

CustomerQuoteSummary的最低字段（均先经目的/目的地白名单）：

| 字段 | 含义 |
| --- | --- |
| `quote_ref, quote_version` | 只读引用与版本；不能单凭引用读取 |
| `product_ref, product_display_name, configuration_display, quantity` | 本次准确拟售SKU/配置与数量 |
| `currency, objective, objective_metric, objective_metric_version` | 币种与已确认现金优化口径；objective=min_customer_payable，metric=min_cash_due_now_given_verified_customer_resources |
| `merchandise_total_minor` | 已核验销售调整后的商品结算应付，支付工具抵付前，不含未计入的必计费用 |
| `mandatory_fees_minor, order_total_before_payment_minor` | 未计入商品结算的全部必计费用，以及抵付前完整订单应付；运费不能默认为0 |
| `credits_applied_minor` | 本方案已经核验可用于本单的非现金支付抵付总额，不包含已算入商品结算的同一减项 |
| `cash_due_now_minor, customer_payable_minor` | 本次现金支付；两字段必须精确相等，后者仅兼容投影，不是第二种价格 |
| `formatted_customer_payable` | 服务端格式化的**本次现金支付**唯一口播金额，LLM不得重算/四舍五入；不另造第二个现金口播值 |
| `customer_resource_snapshot_ref, customer_resource_snapshot_version, resource_use_scope_ref` | 经目的授权的opaque资源引用/版本及允许使用范围；不返回账户号、旧机序列号或证明原件 |
| `customer_resource_usage` | 获准资源消耗/余量数组，包含resource_kind、purpose-scoped resource_ref、unit、consumed_units、applied_amount_minor、remaining_units及适用说明；unit为points、minor_currency等受控枚举，数量为非负整数，不能把点数当金额。已核验无消耗时为[]，未知不可填0 |
| `customer_old_asset_summary` | 单列获准旧机inspected_final_value_minor、inspection_status、voucher_status及本单payment_credit_ref关联；不当额外折扣。无旧机参与且有据时为null，初估不充当最终值；初估/最终值状态不能混用 |
| `customer_visible_conditions, eligibility_status` | 获准必要条件；影响最优的资格unknown不能当有效报价 |
| `customer_visible_breakdown` | 显式批准的客户构成；正式完整包所需分层金额与资源说明不得以空值逃过可解释要求，不返回内部账本/规则全集 |
| `customer_purchase_plan` | `CustomerPurchasePlan`：服务生成并授权的四级适用/互斥解释、同SKU组合比对、适配SKU比较覆盖及最优购买方案；正式marketing/full_package必需，其他仅介绍分支不生成假方案 |
| `minimum_payable_scope` | 最优比较的限定SKU/门店/渠道/时点及范围说明 |
| `valid_until, rule_timezone, dependency_hash` | 时效与任务依赖绑定 |
| `customer_evidence_refs` | 获准对客来源别名；不放机密原文定位/签名URL |

按具体场景可由服务形成`product_and_quantity_sentence`、`customer_visible_conditions_sentence`、`eligibility_confirmation_sentence`、`customer_visible_breakdown_sentence`、`minimum_payable_scope_sentence`和`valid_until_display`等已获准格式化文本，供销售prompt绑定。breakdown句应分别说明商品结算应付、必计费用、已核验抵付与本次现金，另说明旧机价值/积分消耗及余量；所含金额全部由同一冻结账本服务端填入，不让LLM相减。它们只反映同一摘要字段，不增加优惠或承诺。字段外发授权不足以解释现金构成时，采用本地确定性稿或阻断对应对客成品，不能把缺字段稿称为完整可解释报价。

不存在获准报价时整个`customer_quote_summary=null`，不放0元、空金额或占位文本。VALID_OPTIMAL但目的地不获准时也为null，云端不能通过ref自行扩权。

`CustomerPurchasePlan`是客户安全方案摘要，嵌于唯一`CustomerQuoteSummary.customer_purchase_plan`，不维护第二份金额或权限。结构至少包括：

| 字段 | 约束 |
| --- | --- |
| `plan_ref, plan_version, quote_ref, quote_version` | 与当前SKU报价、资源、规则及validation一致，方案引用也须鉴权 |
| `objective_metric, objective_metric_version, customer_resource_snapshot_ref, customer_resource_snapshot_version` | 与本次现金目标和固定资源条件一致 |
| `selected_product_ref, selected_combination_ref` | 服务选择/客户已选的当前最优可行方案；未决定的等价路径须明确为待选，不能冒称已购买/兑换 |
| `level_rows` | 四条按确认名称展示，每条含level_id/display_name、`applicability=applicable/not_applicable/excluded_mutual_exclusion`、已核验客户可见reason/evidence别名、服务格式化的本级金额/支付性质说明；未知资格/缺规则不能填“不适用”或捏造叠加关系 |
| `comparison_rows` | 服务已核验且按白名单生成的安全比对行，区分same_sku_combination与recommended_sku；含安全组合/产品引用、适用条件、商品结算/抵付/现金/资源差异的`comparison_sentence`及必要限制。句中金额由服务直接填槽，不让LLM心算、取搜索价或补造备选 |
| `comparison_coverage` | 本SKU候选完整性、推荐集expected/validated数量、可比/不可比/未完成范围及原因的获准摘要；精确全域枚举/规则/证明仅留服务器。仅展示部分对客行不等于内部只比这几行 |
| `optimal_scope_sentence, resource_usage_sentence, conditions_sentence, valid_until_display` | 服务生成的限定现金最优范围、旧机价值/积分消耗/余量、资格/约束及有效期说明，全部绑定当前快照 |
| `content_channel, scenario_ref, audience_ref` | 绑定本次已确认平台/场景/人群，用于话术适配，不能用改话术改变金额、资格或销售平台 |

`formatted_customer_payable`仍是当前选定方案唯一现金口播值；比较行的完整句由服务按各自已核验结果生成，不能重新拼出第二套当前方案金额。真实只有一个合法组合时必须如实说明“当前核验范围仅此组合”，不得为凑对比编其他优惠；存在多个合法组合时展示最优及有解释价值的获准差异，并如实标明行选取范围。客户摘要可不含内部淘汰细节，但不能用“内部保密”为由对客声称未经证明的最低。完整规则或资格/费用/资源未知导致无法比较时，customer_purchase_plan不生成可发布值，完整包受阻。

### 4.3 继续生成/导出的联合门禁

含真实报价的成稿至少满足：`quote_required=true`、`quote_status=VALID_OPTIMAL`、独立`validation_ref`当前有效、主体/任务/quote_version一致、`client_quote_allowed=true`且本次目的地获准、所有事实/图片/内容/脚本检查通过。正式marketing/full_package还须当前`customer_purchase_plan`完整、四级适用与安全组合比对通过、推荐集比较覆盖/范围声明准确，并通过对应平台/人群/场景话术检查；单个最终金额不足以通过完整包门禁。这些判断由服务/代码给出，不接受LLM写同名字段批准。

客户可见摘要未获准进入云模型时，可以在云端只生成无真实数值的组织结构，再由受控本地确定性模板填入获准字段并验证；私密合成结果不再回流云端。没有本地安全交付能力时阻断对应成品，不宣称云端完整脚本已交付。

### 4.4 有据推荐集与逐SKU比较

先固定销售平台、顾客需求、使用场景和明确硬需求，再从获准知识库产品事实形成适配推荐集。`recommendation_set_ref`绑定该集合的需求/场景版本、准确product_ref/SKU与配置、适配证据、范围和未决项；该引用继续受主体/租户/用途检查。硬需求不满足者不得因低价入选，关键适配事实未知者先补证/追问，不能伪称满足。

对每个入选SKU独立执行solve→validate→client-view：在其适用四级规则及同一顾客已核验资源快照/允许使用范围下，按有据的合法核算顺序求本次现金最低，分别保存quote_ref/version/validation与资源依赖。候选完整性包括销售优惠组合和合法资源使用组合，不能仅枚举折扣后漏掉抵付限制/积分用量对运费的影响。推荐产品集合与单SKU的候选域是两层不同范围，不能用一款SKU的候选完整性证明覆盖全部产品。调用方逐项调用或服务内部逐SKU调度均可，不新增与本合同冲突的批量路径。

获准比较只展示适配理由、必要差异、各SKU最低本次现金及商品结算/抵付/资源消耗/条件/时效，声明“本次适配推荐集内、同一顾客已核验资源条件下的现金比较”；币种、quantity、渠道/地域及时点、资源快照/允许使用范围口径须一致或显式分组。存在缺规则、资源/费用未定、无权限或未证最优候选时显示不完整，不能当成高价排除后宣称全体最低。现金并列而积分/旧机/券消耗不同，不称同等总成本，不暗设兑换或处置偏好；给出获准差异由顾客决定。价格排序不取代需求适配判断，不把某SKU最低、推荐集内最低或全市场最低混称。选定拟售产品后，文案/海报/脚本只绑定其准确SKU和quote_ref/version；需求、资源快照/允许范围或推荐集变化使相关比较结果失效并重检。

## 5 节点调用顺序与六段脚本

节点指南中的报价顺序统一为：

```text
/v1/contexts/resolve → /v1/kb/evidence → /v1/quotes/solve
→ /v1/quotes/{quote_ref}/validate（独立复算，必需）
→ /v1/quotes/{quote_ref}/client-view（本次用途/目的地的客户摘要）
→ /v1/quotes/{quote_ref}/script-input（产品/需求/动作/报价安全绑定）
→ 写作/脚本或受控本地模板
→ /v1/quotes/{quote_ref}/verify-content（金额、条件、范围与保密复核）
→ /v1/artifacts/finalize（源与版本再确认、授权交付）
```

不报价任务跳过所有quote端点；营销海报经内容核验后调用`/v1/renders/poster`，再做实际PNG视觉/版面检查。报价变化使绑定脚本和含金额海报失效，不得只改数字沿用旧检查。

六段脚本唯一时间边界与销售脚本设计/prompt一致：`0–20 / 20–45 / 45–85 / 85–120 / 120–155 / 155–180`秒，预算`20+25+40+35+35+25=180`。分别是确认任务、核型号、相关产品验证、观察与边界、资格/实付解释、有效期与下一步。实际结果和计时由人员/应用记录，不由LLM补填。

## 6 实现与合同测试最低要求

1. 只保留本合同canonical路径；测试节点映射、路径参数quote_ref与body版本一致，不能留另一套设计别名。
2. HTTP200+wrapper ready但quote_status非VALID_OPTIMAL或client_quote_allowed=false时，真实金额/脚本不能继续。
3. 不报价时quote_status=null；当前P4状态只阻断报价及依赖报价的完整脚本，不阻断正常产品营销。
4. 未授权云端只见安全状态/ref；用独特假机密标记扫描节点输入输出/日志/LLM请求，内部规则/候选/证明零外发。
5. 独立validate、client-view、script-input、verify-content、finalize均检查当前主体、目的、目的地、时效、依赖与租户；引用不当访问许可。
6. 金额字段、服务端格式化文本、quote_ref/customer_quote_ref别名及六段Schema做跨文档/跨节点合同测试；quantity/currency/as_of/timezone缺失不静默填值。
7. 超时/取消/源更新/撤权/旧分支迟到不能输出旧有效报价；未实际联调仍标NOT_RUN/BLOCKED。
8. 以满足硬需求的有据推荐集测试逐SKU最优与对比；低价但不适配、跨SKU复用quote、比较口径不同或候选不完整却宣称全体最低均须拦截。
9. 测试现金目标与账本恒等式、customer_payable_minor等值投影、商品结算/抵付的区分；同一旧机与已发代金券重复扣减、积分两处扣减、未来积分/回收初估充余额、未知运费按0、跨SKU采用不同资源快照、无限权益、遗漏合法资源组合均须拦截。
10. 同最低现金而资源消耗不同必须保留可解释差异与余量；仅报价不实际兑换/回收/支付。资源耗用影响运费/限额的夹具须整体回算，独立validate使用同一冻结资源和目标版本证明现金最优。
11. 正式marketing/full_package无customer_purchase_plan、仅有最终价、四级漏项/未知伪装不适用、虚构替代组合或比较覆盖缺口却称全体最低均不得通过；已授权方案字段须在对应平台/场景话术中实质呈现，不能只输出通用卖点。仅一个合法组合的真实说明可通过组合说明要求，但未完成来源/候选核验不能借此逃过比对。

## 9 v1.4 本地开发适配与节点任务包

用户已确认local_snapshot开发＋ima_live/hybrid_verified参赛。原接口路径与报价状态枚举保持一致；模型只消费已授权最小任务包，源目录配置仅服务器可见。最小开发桥接实现不代表本合同所有端点或多门店隔离已实现。

POST /v1/contexts/resolve 返回data.source_context_ref及短期source_context_proof，后者绑定主体、资料范围/模式、源快照和期限，只供下一HTTP请求，不给LLM/公开日志。POST /v1/kb/evidence验证该proof后，用data.task_bundle封装当前节点获准数据；旧字段evidence_set_ref等安全引用可继续在data中提供，内容事实/资产以bundle为单一模型输入。拒绝客户端伪造trusted_context/evidence/allowed_assets。

task_bundle键为trusted_context、task、evidence、allowed_assets、policy、strategy_plan、quote_context、draft、validator_feedback，按节点所需取最小字段。task含task_kind；quote_inputs保留用户已给地区/时点/时区/数量/币种/资格状态或安全引用，不让解析模型验证资格。policy.allowed_model_destinations按node_id/provider/model/purpose_ref/destination_ref/region逐节点核准；未配置不外发事实。proof不是模型可见能力，也不是多门店最终用户身份验证的替代。

所有claims.target、findings.target_ref、coverage.checked_target_refs采用RFC6901 JSON Pointer。事实/业务主张至少有fact_ids/business_rule_ids，quote_binding=null；报价主张quote_binding={quote_ref,quote_version}关联本次有效CustomerQuoteSummary，可无产品fact_id，禁止用内部P4原文证明。服务仍对整稿hash/版本执行verify-content，绑定不能被模型签发。

目前本地P4全是模板，对真实报价一律BLOCKED_SOURCE_UNVERIFIED；新adapter不得用公开快照拼优惠。未实现的端点明确NOT_IMPLEMENTED，不返回模拟成功。
