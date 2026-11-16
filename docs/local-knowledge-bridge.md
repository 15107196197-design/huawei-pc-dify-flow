# 本地只读知识桥接服务

桥接实现版本：0.1，文档状态更新于2026-10-18。源码位于`services/knowledge_bridge/`，桥接本身只用Python标准库。ima认证、单文件原文匹配与**Dify中的scope/evidence→writer/review安全证据输入已真实验证**；该稿件未通过CTA审核，当日ima读取现受额度限制。`quote_engine`与`poster_renderer`已有合成核心测试，报价、PNG业务HTTP适配及完整交付门禁未完成。

## 当前 Dify 连接状态

本机 Dify 1.17.1 已安装并完成初始化，可打开[工作室](http://localhost:8080/apps)。已保存4个本地未发布开发应用：[102节点主应用](http://localhost:8080/apps)、[19节点原产品介绍联调](http://localhost:8080/apps)、[31节点自动修订产品介绍](http://localhost:8080/apps)、[5节点合成图片视觉探测](http://localhost:8080/apps)。DeepSeek Flash/Pro及通义已配置并有真实调用记录；完整主应用仍未验收。

早期真实Dify单步确认：资料范围HTTP成功（0.792秒）；营销降级被Code拦截（1.486秒）；显式产品介绍通过Code（0.220秒）。之后原19节点应用真实写作及审核成功，但文稿因缺配置限定被拦截。31节点自动修订运行`d1405d24-7827-4414-acd9-40bf2444804b`已完成“审核拦截→修订→再次审核通过”，23步、74,464 tokens、240.955秒，仍只输出本地候选。102节点主应用正式报价请求实跑返回`needs_source`。Qwen3-VL-Plus只对自生成`check.png`成功识别形状、颜色及`K7M4`；不是产品图/海报审核。历史402余额问题已在用户充值后恢复，不是当前阻断。

当前 `allowed_assets=[]`、真实报价保持阻断。validate、client-view、script-input、verify-content、render、finalize业务适配尚未完成；产品图片File/视觉闭环、全库及报价/图片的ima复核、多门店认证隔离、真实规则、多SKU覆盖、获准导出及大于95%的报价验收均未完成。独立合成视觉探测不代表主应用图片链已接通，qwen-image-3.0-pro仅有离线适配器26项测试、未真实生成图像。

最新本地运行`371b3173-b9c3-4cd2-b9b4-0f0d58d1d35b`共18步、32,359 tokens、85.24225秒，writer完成但reviewer非法JSON被严格阻断，未进入修订。已新增单独中文格式失败说明；旧失败数据离线重放、UI保存及数据库hash核对均通过，不放宽JSON、不增加模型调用，不算新成品成功。此前`d1405d24…`通过仍保留为历史本地候选。主应用运行`90c23744-ac94-477b-9316-ad987b93619a`为12步、1,542 tokens、10.164221秒，中文说明四级规则、顾客权益和旧机缺项，不产价格。

## 启动与私有配置

在项目根目录运行 Python 3.10 或以上版本。把以下环境变量放在本机受控启动环境；不提交环境文件、凭证、完整源文件清单或业务资料到 GitHub：

- `HUAWEI_KB_ROOT`：用户授权的 v7 根目录绝对路径。目录保持原位只读，不复制进源码仓库；不能是符号链接。
- `HUAWEI_TOOL_TOKEN`：至少 24 字符的随机服务密钥，建议使用 32 字节随机值。所有 HTTP 请求使用 `Authorization: Bearer <secret>`。不要放在 URL、提示词或普通工作流变量里。
- `HUAWEI_ALLOWED_MODEL_DESTINATIONS_JSON`：服务端人工核准的模型目的地 JSON 数组，默认 `[]`。每条必须且只能包含 `node_id/provider/model/purpose_ref/destination_ref/region` 六个非空字符串。实际 provider ID、模型名称须与 Dify 原生模型节点一致，不能用展示名推测。
- `HUAWEI_SOURCE_MODE`：当前私有配置明确为`local_snapshot`，本地模式不读取ima凭据、不联网。
- `HUAWEI_ENABLE_IMA_VERIFICATION`：当前私有配置为`1`，对应`enable_ima_verification=true`，只为受控HTTP显式hybrid请求装配延迟验证器。hybrid失败不降级、不用旧收据冒充实时来源，不接受模型自报库ID或任意下载地址。Dify画布暂无source_mode切换控件，normalizer不让LLM决定来源。

当前固定开发身份：`actor_id=local_developer`、`tenant_id=development_only`、`store_id=local_single_store`；用途 `purpose_ref=local_product_content`、目的地 `destination_ref=local_dify`、地域 `region=CN`。这些值由应用凭证映射，不从请求体中的自报身份派生。请求若显式提交其他范围会被拒绝。**尚未实现真实最终用户认证、多门店权限映射、密钥轮换、生产审计或多租户上线权限。** 不得把此服务直接当多门店上线版本。

白名单格式示意（尖括号内容必须由管理员替换，示例本身不证明实际调用获准）：

```json
[
  {"node_id":"product_intro","provider":"<实际Dify provider ID>","model":"<实际型号>","purpose_ref":"local_product_content","destination_ref":"local_dify","region":"CN"},
  {"node_id":"fact_compliance_review","provider":"<实际Dify provider ID>","model":"<实际型号>","purpose_ref":"local_product_content","destination_ref":"local_dify","region":"CN"}
]
```

该显式配置授权最小产品事实及出处 payload 向所列用途/节点/模型/地域披露，不授权 P4、报价、凭证或任意原文目录。产品介绍需 `product_intro` 和 `fact_compliance_review` 分别匹配；营销候选还需对应 `article_write` 或 `poster_copy`、`platform_strategy/visual_layout/visual_review`，含报价或脚本另需 `quote_explain/sales_demo`。这些白名单是必要条件，不能使未实现的功能自动可用。服务不验证供应商余额或账号可用性，也不选择替代供应商；调用前须核对**实际节点**的 provider/model/node_id。变更私有白名单后重启服务，旧上下文失效。

```sh
python3 -m services.knowledge_bridge audit
python3 -m services.knowledge_bridge search 'MateBook Pro S'
python3 -m services.knowledge_bridge serve
```

默认监听 `127.0.0.1:8765`，仅接受 loopback 地址；可用 `--port` 修改端口。开发 HTTP 不提供 TLS，不允许借此例外对局域网或公网开放。本机部署已设置受限的容器→主机访问路径，且已由真实 Dify 资料范围 HTTP 单步验证；路径与凭证使用私有配置，不据此推定其他接口或模型也已接通。此 Python 服务本身不创建穿透或公网监听。

`audit/search` CLI读取同一套本地根目录和服务配置，不调用网络或消费模型额度。`serve`在明确启用hybrid模式后才会延迟读取本机私密ima凭据并调用受限官方接口；本地模式不因此联网。没有模型白名单时仍可在本地终端检索事实；HTTP evidence不会返回可交给模型的事实payload。

## 已实现端点与短期 proof

通用响应：`{request_id,status,data,error}`。包装状态为 `ready/needs_input/needs_source/conflict/denied/error`；被安全处理的业务阻断通常 HTTP 200，认证失败 HTTP 401，范围/proof拒绝 HTTP 403，源变化/过期 HTTP 409，未实现接口 HTTP 501。HTTP 200 或 `ready` 不代表成品、来源真实性、图片授权、比赛资格或导出已验收。

### 1. `POST /v1/contexts/resolve`

请求中的 `task` 是对象，允许 `task_kind`、产品原话、人群、使用场景、购买阶段、问题、目标、渠道、销售平台、报价/脚本标记，以及可选字符串数组 `hard_requirements/required_fact_fields`。仅保留白名单字段、验证类型和枚举；丢弃客户端 `trusted_context/evidence/allowed_assets/policy` 等伪可信字段。

```json
{"task":{"task_kind":"product_intro","product_query":"MateBook Pro S","audience":"顾客","usage_scenario":"日常办公","quote_required":false,"script_required":false}}
```

`data` 返回 `source_context_ref/source_context_proof/source_snapshot_ref/source_mode/purpose_ref/destination_ref/expires_at/policy` 和安全报价状态。签名 proof 由服务随机密钥 HMAC-SHA256 产生，绑定固定主体/门店/用途/目的地/地域、源快照、任务 hash 与期限，默认 120 秒。proof 不能代替 Bearer 认证；服务还核对内存中的原始上下文。服务重启、过期或源变化后必须重新 resolve。

**proof 仅传给下一受控 HTTP 请求的 `X-Source-Context-Proof` Header**，不得进入模型、聊天展示、公开日志或稿件。调用方不得自行解码后重签，也不得把编码内容当授权。服务不把 proof 放入 `task_bundle`，服务访问日志已关闭；Dify 调试记录的字段遮蔽与访问控制仍须单独验收，不能声称平台全部日志已遮蔽。

### 2. `POST /v1/kb/evidence`

需 Bearer 和上述 proof Header；请求体最小为 `{source_context_ref,task}`。task 清洗后必须与 resolve 时完全一致。若另传 `product_query/content_channel/sales_platform`，也须与绑定 task 一致。支持布尔 `need_product_facts/need_pricing_rules/need_images`，不接收任意 URL 或路径。

正常无报价取证返回 `data.task_bundle`：

```text
trusted_context: source_context_ref, source_mode=local_snapshot,
                 source_snapshot_ref, competition_eligible=false,
                 ima_provenance=unverified, development_single_user_only=true
task: 服务清洗并绑定的任务
evidence: facts[], source_refs[], business_rules=[]
allowed_assets: []
policy: llm_payload_allowed, required_model_nodes[],
        allowed_model_destinations[], source_mode, competition_eligible,
        export_allowed=false, development_single_user_only,
        multi_store_authorization_implemented=false
quote_context: quote_required=false, quote_status=null, quote_ref=null,
               client_quote_allowed=false, customer_quote_summary=null,
               local_delivery_ref=null
```

`facts[]` 具有 `fact_id/product_ref/product_display_name/sku_scope/field_name/raw_value/source_ref_ids/conditions/verification_state`；`source_refs[]` 具有 `source_ref_id/source_title/document_id/content_hash/section_heading/line_start/line_end/source_urls/captured_at/source_excerpt/source_type`。出处 URL 只保留无 query/fragment 的指定华为消费者官网 HTTPS 来源，不发鉴权 URL。`raw_value/source_excerpt` 连同原文单位、脚注和版本条件保留，不调用模型摘要代替取证。文首销售版本限定及显式全局条件单独形成必需出处，加入每个事实的条件与引用；段落中的非星号限制仍完整保存在 raw_value。包装清单保留其款式限制，跳站界面文字不进入事实。显式必需章节缺失返回 needs_source。模型输入不包含源根目录或本机绝对路径。

仅从产品矩阵白名单对应的 `P1/01` 与 `P1/02` 基础 `产品事实.md` 逐 `##` 章节提取；10 型号全量支持，矩阵与官方标题的简称可能不同。没有足够完整型号时返回 `needs_input`；例如 `MateBook 14` 有鸿蒙与酷睿 Ultra 两候选，不能静默选一款。

P4、P1价格快照、P2话术、P5培训、P6旧成稿、研究底稿、待审核与历史稿均不用于证明产品事实；P4为空不会阻断无报价任务。已知异常的四个 Windows 型号尺寸章节，以及 MateBook14 鸿蒙版系统/内存冲突，默认排除；任务明确依赖这些字段或相关硬需求时返回 `conflict`。这是针对当前审计的保守隔离，不能代替完整自动事实冲突检测或真正的硬需求推荐求解器。

图片请求只会在 `data.asset_candidates` 返回已明确型号索引下的**未核验候选元数据**，`rights_state/model_scope_state/ima_provenance=unverified`、`approved_for_publication=false`，不暴露图片字节、绝对路径或可抓取 URL。59 张联合表空型号图片不会按文件名猜归属，其他明确型号图也没有因为完整性检查而获得权利/型号核验。`allowed_assets` 始终为空，因此不能据此宣称已完成配图、海报或 PNG 渲染。

没有完整私有模型白名单时，evidence返回`needs_source`、`reason=MODEL_DESTINATION_NOT_APPROVED`、`task_bundle=null`，不泄露事实payload；不会信任请求体允许标记。`ima_live`尚未实现。知识服务hybrid逐文件核验实跑5.843秒，目标原文3,624字节与本地哈希一致，14条事实、0张获准图片。Dify运行`e4d50529-a519-4fe4-a3bb-14cce80d4e4b`已实际scope/evidence取证并将安全receipt传给writer/review，18步、33,339 tokens、85.24687秒；唯一无证“到店核对”CTA及`needs_human_review=true`使gate/revision阻断，来源接入成功不等于成稿通过。全库核验、参赛资格、导出均为false。

当前get_knowledge_list返回HTTP200、业务码`220021`，官方说明“资料获取次数已达上限，请明天再尝试”，凭据仍有效。今日停止继续读取，不绕过额度；后续`ec297fca…`运行在scope阻断，7步、0 tokens、4.736秒。显式hybrid返回来源额度缺项而非自动切换本地。访问头兼容只允许`X-IMA-Resource-Category`为空，其余五项仍非空；不扩大下载地址或任意Header权限。

### 3. `POST /v1/quotes/solve`

验证 Bearer、范围和 proof 后始终返回 `needs_source`、`quote_status=BLOCKED_SOURCE_UNVERIFIED`、`reason=FOUR_LEVELS_PENDING`，无金额、无 quote_ref、无客户摘要。请求中的假金额/假规则不会被采纳。evidence 请求报价规则，或绑定任务是 quote/sales_script/full_package、明确需要报价时，同样安全阻断；不从公开页面价减券、推国补或编造最低实付。

其余路径和已覆盖的非POST方法返回`error/NOT_IMPLEMENTED`，包括validate、client-view、script-input、verify-content、render、finalize。没有面向调用者的原图下载、写回、上传、删除或任意URL获取接口；hybrid内部原文下载仅使用刚核验的服务访问能力，不对模型开放地址和Headers。

## 下一步适配现有核心：尚未实施

不修改现有失败状态来假装接通。先实现受认证端点、受控运行存储和严格 Schema，再逐项绑定 Dify 节点；以下模块名只供开发者使用，不放入店员或顾客的正常话术。

### 报价核心到业务端点

1. 服务从获准来源取得完整规则，校验真实发布状态、适用 SKU/平台/地域/时效、四级依据和核算顺序；核实同一顾客权益、旧机、余额及允许使用范围。由服务构造 `QuoteContext/RuleSet/ResourceSnapshot`，不接收模型自报已核验资格，不将合成夹具导入业务规则。
2. `/v1/quotes/solve` 调用 `QuoteEngine.solve()`，将 `internal_quote`、完整候选、资源账本及依赖 hash 保存于受控服务。Dify 只取安全状态和引用；不得序列化内部结果给模型。目标是同一已核验资源条件下本次现金最低，不能用商品应付或未来返分替代。
3. `/validate` 加载同版本记录调用 `QuoteEngine.validate()`，并重验来源、权限、时效及候选完整性。核心测试/复算通过仍不签发对客有效价：合成结果维持 `SYNTHETIC_TEST_ONLY`；非合成核心也只得到 `CORE_VALIDATED_NOT_RELEASED`。由完整业务门禁决定是否提升 `VALID_OPTIMAL`，不能仅修改一个状态字段。
4. `/client-view` 每次重新检查主体、目的、模型/目的地与字段许可后，构造 `CustomerQuoteSummary` 和其中唯一 `customer_purchase_plan`。四级适用/互斥、合法组合对照、固定顾客资源、现金与商品应付/抵付差别、条件和有效期都由服务格式化；单个金额不足以交付。多 SKU 未完整覆盖时阻断全推荐集最低结论。
5. 接着实现 `/script-input` 的产品/需求/动作/报价绑定、`/verify-content` 的金额与条件核验、`/finalize` 的当前来源/版本/交付权限检查；对齐画布请求变量并实测。当前这些端点仍501，不能因已存在求解类而放行。

### 海报核心到真实 PNG 与视觉检查

1. 当前图片仅是候选，`allowed_assets` 为空。先核验真实原图的来源、具体 SKU/配置、使用权、有效状态和画面旧价；参赛严格模式还须实际 ima 复核。文件存在、哈希或合成测试不证明授权，不能自行把候选改为 `VerifiedAsset`。
2. 由服务签发并验证 `RenderAuthorization`，绑定当前文稿、独立审核、布局、原图/配置/权利、来源及必要报价/计划。将这些记录和真实原图字节构造成 `PosterRequest`，调用 `render_poster(..., authorization_verifier=...)`。在实际服务 Python 中检查 Pillow 和中文字体；依赖不足明确受阻，不依赖开发机测试的偶然可用性。
3. 私有保存返回的 PNG 字节、文字框、哈希和版本引用，提供每次验权的下载。`PosterResult.status=rendered_pending_visual_review`、`requires_visual_review=true`、`export_authorized=false`，不表示图片已可发布或参赛。
4. 单独实现真实图片进入 Dify File/视觉节点的接线及审核记录，再连接营销视觉后的脚本与最终交付。JSON 中的 `png_ref`、图注或布局说明不能代替像素，当前 File 接线仍明确阻断。生成式图片默认不用于比赛成品，也不替代知识库产品主图。

每一步先在本机做真实 HTTP 成功/失败合同测试，再在 Dify 单步与整条流程验证。未补齐真实资料、权限或视觉输入时，对客只需说明“这份报价尚未完成核验”或需要补核的条件，不展示501、proof、内部规则或调试过程。

## 源变更、路径与日志

上下文快照包含源目录中普通文件相对路径、字节、mtime、inode 和 SHA256；resolve、evidence 前后重新检查。目录内出现符号链接即拒绝，不跟随链接。实际读取使用根目录 fd、逐层 `O_NOFOLLOW` 与相对目录 fd，拒绝绝对路径、`..`、URL、根替换和不在白名单中的事实路径，防止矩阵指定 P4 或根外文件。源目录上限 20,000 文件 / 256 MiB，单文本上限 4 MiB；超限安全返回，不自动扩大或删除源内容。

任何源文件更新都会让此前 proof/snapshot 失效，须重新取证。服务没有持久稿件依赖库和最终 finalize，因此不能替其他应用自动作废所有已保存的成品；下游必须保留快照绑定、消费时重验，不能沿用旧稿检查。

HTTP 请求日志被关闭，不记录 Header、token、proof、URL路径或业务正文；错误仅返回安全码和固定说明，不返回异常栈或本机路径。此选择适用于本机开发，不是完整生产审计日志方案。

## 已执行验证

```sh
python3 -m unittest discover -s tests -p test_knowledge_bridge.py -v
```

此前已执行的合成临时目录验证覆盖：认证、伪可信 payload、篡改/缺失/过期 proof、跨主体/门店/用途/目的地、任务变更、源变更、根外/任意URL/矩阵及图片索引越权注入、文件及目录符号链接、型号歧义、字段隔离/依赖冲突、全局条件保留、显式必需事实缺失、无报价放行、全部报价阻断、未实现接口、双节点/地域目的地白名单，以及真实本地 HTTP resolve→evidence 和认证错误封装。用例数量和最新结果以本次运行记录为准，不把测试夹具当真实知识库授权。

本轮来源子集已真实回归191项、1.344秒，命令为`python3 -m unittest tests.test_ima_adapter tests.test_ima_content tests.test_ima_hybrid tests.test_ima_runtime tests.test_hybrid_bridge tests.test_knowledge_bridge -q`。此为指定模块子集，不能把191记为全项目总数；另用含Pillow的workspace Python实跑全套471项，全部通过、5.326秒、无跳过。

实际授权v7目录只读CLI冒烟通过：1,522文件、10型号、20/20 P4空模板；`MateBook Pro S`返回14个事实及15个出处（含全局条件）；`MateBook 14`返回2候选与needs_input。ima单文件原文3,624字节匹配及Dify安全证据输入已验证，不覆盖全库、图片权利或真实价格。私有安全记录位于`.local/runtime-evidence/ima-hybrid-bridge-live.json`，不得公开凭据、proof、原文或签名地址。当前因每日读取额度阻断hybrid，最新本地文本因非法JSON阻断；真实图片审批、报价与参赛验收未完成。两个当前画布10个System及12个Code（4个Scope/EVIDENCE、8个格式处理）已与来源精确核对并确认数据库持久化；旧19节点应用不冒称当前版本。

### 审核格式失败的 Dify 单步验证（2026-10-18）

在31节点开发应用的`revision_feedback`中，使用缓存的真实失败输入执行新代码，Dify单步状态为`SUCCESS`、0.924秒、0 tokens；业务输出为`ready=false`、`payload_json={}`、proof与scope_ref为空，并显示固定中文格式错误说明。该结果只证明此Code节点在Dify中安全阻断，未重新调用模型或重跑整条流程，不是产品介绍或参赛成品通过记录。
