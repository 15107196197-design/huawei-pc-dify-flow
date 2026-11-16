# 完整能力配置手册

这份文档回答一个问题：**要让它真的走通"给顾客报价 + 出图"，我需要在自己机器上配哪些东西？**

不是所有能力都需要配。先把目标分级，选你要的那一级，别一上来就配全套。

---

## 0 · 能力分级：先决定你要走到哪一级

| 级别 | 能做到 | 需要配的东西 | 大致耗时 |
|---|---|---|---|
| **L1 结构通** | 打开 112 节点画布、对话能跑、产出营销文本 | Dify 1.17.x + DeepSeek 插件 + 1 个文本模型 | 20 分钟 |
| **L2 有依据** | 文案里的产品事实来自你自己的资料，不是模型编的 | L1 + 知识桥接（`HUAWEI_KB_ROOT` + Token） | +30 分钟 |
| **L3 能报价** | 给出四级方案的确定性计算结果（不是模型算的） | L2 + 你自己的商业规则 JSON | +1–2 小时（**主要时间花在整理规则，不在配置**） |
| **L4 出图** | 排版出海报 PNG，图片过内容审核 | L3 + Pillow + 通义图像能力 | +40 分钟 |

**L3 是本项目的分水岭。** 前两级解决"说得像专业销售"，第三级才解决"数字对不对"。绝大多数人在 L3 卡住不是因为技术，而是因为**没有可用的价格规则数据**——这是数据问题，不是配置问题。

---

## 1 · 环境基线

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Dify | **1.17.x** | 作者验证于 1.17.1（commit `8387590ace4a094de812b7847fc6a4c3a27cd52b`）。DSL 基于 Graphon 0.7.0 |
| Python（跑工具服务） | 3.10+ | 桥接、报价、渲染都用标准库；**只有海报渲染需要 Pillow** |
| Pillow | 任意近期版本 | 只影响海报像素测试与渲染，缺了会明确跳过并标注 |
| 磁盘 | 10 GB+ | Dify 本体 + 镜像 |

**装 Dify 三条路，按你的情况选：**

| 方式 | 适合 | 代价 |
|---|---|---|
| 官方 Docker Compose | 已有 Docker / Linux 服务器 | 最快，但会占用全局 Docker |
| Dify Cloud | 只想试画布 | 版本可能比 1.17 新，导入后要核对节点 |
| 本仓库 `deploy/dify-local/`（Lima 虚拟机 + rootless Docker） | macOS，不想装 Docker Desktop | 多 20–30 分钟，多约 12 GB 磁盘 |

第三条是本项目作者实际用的方案，细节见 [deploy/dify-local/README.md](../deploy/dify-local/README.md)。它的好处是：不改系统登录项、不开公网端口、只在 `127.0.0.1:8080` 暴露。

---

## 2 · 画布：五个应用，按顺序导入

生成（仓库不直接分发 DSL）：

```sh
python3 scripts/build_full_dify_bundle.py --out ./apps
```

| 顺序 | 应用 | 节点/连线 | 先导它的理由 |
|---|---|---|---|
| 1 | 合成图片 · 视觉连通测试 | 5 / 4 | 最容易通，验证"模型 + 文件输入"这条基础链路 |
| 2 | 本地资料产品介绍最短链 | 19 / 18 | 验证"查资料 → 写介绍"，不需要报价规则 |
| 3 | 平台策略分阶段模型联调 | 16 / 19 | 验证"不同阶段用不同模型"的可行性 |
| 4 | 产品介绍写审修订链 | 31 / 33 | 验证"写作 → 独立审核 → 修订"三跳闭环 |
| 5 | 完整路由主应用 | 112 / 170 | 全链路，最后上 |

**导入步骤**：Dify 工作室 →「创建空白应用」→ 导入 DSL 文件 → 选 `full-workflow.candidate.yml`。

**验证标准**（缺一不可）：
- 画布完整渲染，节点无红色报错块
- 保存后关闭再重开，节点数不变（排除导入时静默丢节点）
- 单个 LLM 节点做一次"运行此节点"，能返回非空内容

---

## 3 · 模型：插件、槽位、以及"两个模型必须不同"

### 3.1 要装的插件

| 插件 | 版本（作者验证） | 用途 |
|---|---|---|
| `langgenius/deepseek` | 0.0.24 | 全部文本：写作、策略、审核、解释 |
| `langgenius/tongyi` | 0.2.23 | 生图（qwen-image）+ 审图（Qwen3-VL-Plus） |

DSL 里的 `dependencies` 是空的，**插件不会自动安装**，必须在「设置 → 插件」里手动装。

### 3.2 八个模型槽位

画布用槽位名而不是固定模型名思考，槽位定义见 `scripts/build_full_dify_bundle.py` 的 `MODEL_SLOTS`：

| 槽位 | 干什么 | 建议 |
|---|---|---|
| `MODEL_PARSE` | 场景解析（顾客一句话 → 结构化任务） | 快而便宜的模型 |
| `MODEL_WRITE` | 写文案 / 产品介绍 / 海报文案 | 质量优先 |
| `MODEL_STRATEGY` | 平台策略（公众号 vs 小红书 vs 门店） | 中等模型够用 |
| `MODEL_REVIEW` | 独立审核 | **必须与 `MODEL_WRITE` 不同** |
| `MODEL_QUOTE` | 把计算结果讲成人话 | 不参与计算，只管表达 |
| `MODEL_LAYOUT` | 海报版面文案 | 短文本，便宜的即可 |
| `MODEL_SCRIPT` | 三分钟对客讲解 | 质量优先 |
| `MODEL_VISION` | 图片内容审核 | 需要视觉模型 |

**`MODEL_REVIEW` ≠ `MODEL_WRITE` 是硬规则。** 同一个模型自己写完自己审，审核门禁就形同虚设。这是本项目的核心设计取舍之一。

### 3.3 模型名的坑

DSL 里写死的两个名字——`deepseek-flash`（写作）、`deepseek-v4-pro`（审核）——是**作者环境里插件声明的名字**，不是 DeepSeek 官方固定 ID。你装完插件后下拉里可能是 `deepseek-chat` / `deepseek-reasoner`。

处理方式：

```sh
# 先确认你环境里究竟有哪些模型名
# Dify 页面：设置 → 模型供应商 → DeepSeek → 查看模型列表
```

然后画布上逐个改 14 个 LLM 节点的模型选择。**改完记得写作与审核挑两个不同的。**

### 3.4 连接定义（可选，进阶）

`specs/model-routing.example.json` 里给了三条连接的抽象定义：

| connection_ref | adapter | 说明 |
|---|---|---|
| `deepseek` | `text_openai_compatible` | 标准 OpenAI 兼容接口 |
| `bailian` | `native_dify_provider_or_verified_compatible` | 百炼原生或已验证兼容 |
| `bailian_image` | `bailian_image_generation_editing` | 图像生成与编辑 |

这个文件是**设计记录**，不是运行时配置，直接改它不会生效。它的价值是告诉你：换成别的供应商时，该找哪种 adapter 类型。

---

## 4 · 知识源：让文案里的事实有出处

### 4.1 两种模式

| 模式 | 数据从哪来 | 公开仓库可用？ |
|---|---|---|
| `local` | 你本机一个只读目录 | ✅ 可用 |
| `hybrid_verified` / `ima` | ima 共享库 OpenAPI 实时核验 | ❌ **不可用**——`services/ima_adapter/` 不在公开仓库里 |

这一点必须说清楚：**公开版只能走 `local` 模式。** 原作者用的 ima 实时核验涉及私有适配层，没有随仓库发布。

### 4.2 起桥接（L2 的核心动作）

桥接是一个**只在本机回环地址监听**的 Python 服务，负责"把允许的文件按允许的方式交出去"。

```sh
export HUAWEI_KB_ROOT="/绝对路径/你的资料目录"     # 只读根目录，必须
export HUAWEI_TOOL_TOKEN="自己生成一串随机字符"      # 服务鉴权，必须
export HUAWEI_SOURCE_MODE="local"                    # 默认 local
export HUAWEI_ALLOWED_MODEL_DESTINATIONS_JSON='[]'   # 允许外发给模型的字段白名单，先留空

python3 -m services.knowledge_bridge audit     # 1) 先体检：目录结构、文件类型、可读性
python3 -m services.knowledge_bridge search "MateBook Pro S"   # 2) 试检索
python3 -m services.knowledge_bridge serve    # 3) 起服务，默认 127.0.0.1:8765
```

参数：`serve --host 127.0.0.1 --port 8765`。**不要改成 0.0.0.0**——这个服务没有 TLS，一旦监听外网就等于把资料目录交出去。

### 4.3 五条安全约束（写死在代码里，不是建议）

| 约束 | 违反时返回 |
|---|---|
| 路径必须在 `HUAWEI_KB_ROOT` 之内 | `SOURCE_PATH_REJECTED` / 403 |
| 不许符号链接逃逸 | `SOURCE_PATH_REJECTED` / 403 |
| 只认普通文件，不认设备/管道 | `SOURCE_PATH_REJECTED` / 403 |
| 必须带正确 Token | `AUTH_REQUIRED` / 401 |
| 请求的身份/披露范围必须匹配 | `SCOPE_MISMATCH` / 403 |

另外 `HUAWEI_ALLOWED_MODEL_DESTINATIONS_JSON` 控制"哪些字段允许发给模型"。默认空 = 什么都不外发。填的时候要按字段逐项放行，不要图省事写全放。

### 4.4 容器访问本机：为什么 127.0.0.1 不通

Dify 跑在容器里，容器里的 `127.0.0.1` 指的是容器自己，不是你的 Mac。所以 `http-request` 节点写 `http://127.0.0.1:8765` 会失败。

本仓库给的解法是 **squid 桥接**：

```sh
python3 deploy/dify-local/generate-bridge-squid.py     # 生成 squid 配置
python3 deploy/dify-local/probe-bridge-network.py      # 探测容器 → 主机通路
```

原理和边界见 [docs/local-bridge-network-plan.md](local-bridge-network-plan.md)。这对"只放行指定入口、其余 403"的设计由测试 `tests/test_bridge_squid_policy.py` 守着。

---

## 5 · 报价：四级方案怎么算

### 5.1 四级是什么

| level_id | 显示名 | 含义 |
|---|---|---|
| `base_price` | 基准价 | 商品本身价格 |
| `platform_discount` | 平台优惠 | 平台券/活动立减 |
| `identity_benefit` | 身份权益 | 学生/教师/会员等身份权益 |
| `trade_in_national_subsidy` | 换新国补 | 以旧换新 + 国家补贴 |

计算目标固定为 **`min_customer_payable`**：在已核验的顾客资源下，本次最低实付。核心语义写在 `specs/quote-configuration.example.json` 的 `payment_semantics` 里，其中两条最关键：

- `missing_fee_is_not_zero: true` —— **缺的费用不能当 0 算**，缺就是缺，报价阻断
- `allow_future_rewards_as_current_resources: false` —— 未来的返现不能当现在能用的钱

### 5.2 这两个 example 文件**不能直接用来报真价**

| 文件 | 状态字段 | 含义 |
|---|---|---|
| `specs/quote-configuration.example.json` | `configuration_state: "example_not_ready_for_real_quotes"` | 结构范例，不是可用配置 |
| `specs/commerce-rule-candidate.example.json` | `candidate_status: "pending_kb_ingestion"`、`real_quote_enabled: false` | 候选映射，还没入知识库 |

作者自己在文档里也写明了：**P4 全部 20 份仍是空模板**，141 条公开价格快照不能代替四级结算规则。

### 5.3 要让它真报价，你需要自己准备

1. **商品基准价**：型号 → 价格，带版本号和生效时间
2. **优惠规则**：平台券的适用条件、叠加顺序、互斥关系、每人限次
3. **身份权益**：哪些身份、需要什么凭证、能不能与其他优惠叠加
4. **换新与国补**：旧机估价规则、补贴上限、地区差异、与平台优惠的先后
5. **资格校验**：什么情况下这条规则不适用（**这一项比价格本身更重要**）

把它整理成 `commerce-rule-candidate.example.json` 那种结构的 JSON，`real_quote_enabled` 置 `true`，再让 `services/quote_engine/engine.py` 读它。

**提醒**：`quote_engine` 是确定性代码，它不会"猜"。规则没覆盖到的组合，它会返回缺口而不是给个近似值。这是对的，但你得接受"配置不全时它什么都不给"。

---

## 6 · 图片与海报

| 组件 | 作用 | 依赖 |
|---|---|---|
| `services/poster_renderer/renderer.py` | 确定性排版出 PNG（不靠模型画） | **Pillow** |
| `services/image_provider/qwen_image.py` | 调通义生图/改图 | `langgenius/tongyi` + 百炼权限 |
| 视觉审核节点 | 检查图片内容是否合规 | Qwen3-VL-Plus（视觉模型） |

设计取向：**版式用代码算，图才用模型生成。** 所以海报的文字位置、字号、留白是确定的，不会每次跑都不一样；模型只负责"画面内容"。

装 Pillow：

```sh
python3 -m pip install Pillow
python3 -m unittest discover -s tests -p "test_poster_renderer.py" -v
```

缺 Pillow 时测试会**明确 skip 并标注**，不算通过——这是刻意的，避免"跳过当通过"。

---

## 7 · 验收：怎么知道真的通了

### 7.1 三层验证，别混着说

| 层次 | 怎么验 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| 离线合成测试 | `python3 -m unittest discover -s tests -v` | 代码逻辑对不对（157 项） | 模型好不好、准不准 |
| 单点真实调用 | 画布上"运行此节点" | 这个节点能通到模型 | 整条链路能跑 |
| 端到端验收 | `docs/acceptance-cases.csv` 的 133 条 | 业务是否真的可用 | — |

**133 条目前全部 NOT_RUN。** 这不是没做，是没通过。导入成功、单点跑通，都不等于业务可用。

### 7.2 建议的自测顺序

```sh
# 1. 离线先跑绿，排除代码问题
python3 -m unittest discover -s tests -v

# 2. 桥接体检
python3 -m services.knowledge_bridge audit

# 3. 报价引擎单测
python3 -m unittest tests.test_quote_engine -v

# 4. 再上画布，从 5 节点那个开始
```

---

## 8 · 配置检查清单

按你要的级别勾：

**L1 结构通**
- [ ] Dify 是 1.17.x
- [ ] DSL 已生成（`manifest.json` 里 112 节点 / 170 连线）
- [ ] 导入后重开节点数不变
- [ ] `langgenius/deepseek` 已装
- [ ] 14 个 LLM 节点指向实际存在的模型名
- [ ] 写作模型 ≠ 审核模型

**L2 有依据**
- [ ] `HUAWEI_KB_ROOT` 指向一个只读目录
- [ ] `HUAWEI_TOOL_TOKEN` 已设且不是弱口令
- [ ] `audit` 无报错
- [ ] `search` 能查到东西
- [ ] 容器内能访问到桥接（squid 已配，`probe-bridge-network.py` 通过）
- [ ] `HUAWEI_ALLOWED_MODEL_DESTINATIONS_JSON` 是逐字段白名单，不是全放

**L3 能报价**
- [ ] 四级规则各有真实数据来源与版本号
- [ ] 规则里写清了叠加顺序与互斥关系
- [ ] `missing_fee_is_not_zero` 语义被遵守（缺费不补 0）
- [ ] `real_quote_enabled` 已在你自己那份配置里置真
- [ ] 抽样 5 个真实场景，人工核对计算结果

**L4 出图**
- [ ] Pillow 已装，海报测试不再 skip
- [ ] `bailian_image` 连接可用
- [ ] 视觉审核节点能返回结论
- [ ] 同一输入重复跑两次，版式一致（证明是确定性排版）

---

## 9 · 还配不出来的部分（诚实清单）

| 能力 | 为什么配不出来 |
|---|---|
| ima 共享库实时核验 | `services/ima_adapter/` 未随公开仓库发布 |
| 真实四级最低实付 | 缺真实价格规则数据（P4 空模板） |
| 产品图闭环 | 需要你自己的合规图源 + 发布权利 |
| 门店隔离 | 设计已写，未实现验收 |
| 导出成品 | NOT_RUN |

这些不是配置问题，是**没做完或不能公开**。想往下走，得自己补实现或补数据。
