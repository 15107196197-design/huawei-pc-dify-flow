# 华为PC场景营销、报价与讲解智能体

> 公开源码副本：不包含用户知识库、原图、私有取证底稿、运行时DSL或凭证。本机应用链接已改为自行部署后的工作室入口；具体能力以本仓库README当前状态为准。

把"给顾客讲清一台 PC 值不值得买、到底要花多少钱"这件事，拆成 112 个可审计的画布节点：输入一句产品需求，依次过场景解析 → 平台策略 → 图文软文 → 图文核验 → 四级购买方案 → 三分钟对客讲解 → 复制导出。

**这不是一个可以直接上线的产品。** 133 条验收规格全部 NOT_RUN；真实报价、产品图闭环、门店隔离、导出这几项都没有验收通过。下面每一处都按实际验证状态标注，不夸大。

> **同一项目的另一条路线**：完整工作台版（Python 服务端 + 前端，可真实调用模型、计算四级报价、渲染海报）在 <https://github.com/15107196197-design/huawei-pc-workbench>。本仓库是 **Dify 画布版**——重点在流程结构与提示词，适合导入 Dify 后改画布；工作台版重点在能跑起来的完整应用。两者可对照阅读。

---

## 一、你能怎么用它

按你想投入的时间，选一条走：

| 路径 | 适合谁 | 需要多久 | 从哪开始 |
|---|---|---|---|
| **① 只看效果** | 想快速了解这东西长什么样 | 0 分钟 | 打开 [ModelScope 创空间](https://modelscope.cn/studios/A1211JOY/huawei-pc-agent)（公开演示，无需配置；不调模型，是交互式样机） |
| **② 让画布在你自己的 Dify 里跑起来** | 想改提示词、想学画布怎么搭 | 约 20 分钟 | [QUICKSTART.md](QUICKSTART.md) |
| **③ 复刻全部能力**（真实模型调用＋本地知识库＋报价计算＋海报渲染） | 想二次开发或做同类作品 | 半天起 | [docs/HOW-TO-CONFIGURE.md](docs/HOW-TO-CONFIGURE.md) |

路径 ② 走完，你能得到一个"能对话、能产出营销文本"的应用；路径 ③ 才可能走通"带真实报价和海报"的完整链路——因为后者的每一环都依赖你本机的额外组件，见下一节。

---

## 二、它由什么组成

```
                        ┌─────────────────────────────────────────┐
   顾客一句话  ────────► │  Dify Chatflow（本仓库生成，112 节点）    │
   「MateBook 给大学新生」│  14×LLM  37×Code  38×If-Else  12×HTTP   │
                        └───────┬─────────────────────┬───────────┘
                                │ HTTP（12 个请求节点）  │ 模型调用
                                ▼                     ▼
              ┌──────────────────────────┐   ┌──────────────────┐
              │ 本机业务工具（Python 标准库）│   │ DeepSeek / 通义   │
              │  • quote_engine  四级报价  │   │ 写作  deepseek-*  │
              │  • poster_renderer 海报排版│   │ 审核  deepseek-*  │
              │  • knowledge_bridge 知识源 │   │ 生图  qwen-image  │
              │  • image_provider 生图适配 │   │ 审图  Qwen3-VL    │
              └──────────┬───────────────┘   └──────────────────┘
                         │ 只读、带 Token、按模型白名单放行
                         ▼
              ┌──────────────────────────┐
              │ 你的本地资料 / ima 共享库  │
              └──────────────────────────┘
```

设计上有一条硬规矩：**模型不许直接算钱、不许直接下结论。** 价格由 `quote_engine` 的确定性代码算，事实由知识源核验，模型只负责表达和审核。所以任何一环没配好，它会**明确阻断**（fail closed），而不是编一个看起来合理的数字给你。

---

## 三、能力 → 你需要配什么

这张表是全文最重要的一张。**左边是你想要的能力，右边是它真正的依赖。**

| 能力 | 依赖组件 | 不配会怎样 |
|---|---|---|
| 对话跑通、产出营销文案 | 一个 Dify 1.17.x 实例 + DeepSeek 插件与 API Key | 画布打不开节点 / LLM 节点报模型不存在 |
| 独立审核（写作与审核必须是不同模型） | 两个可用文本模型 | 审核节点直接拦下，不出稿 |
| 引用真实产品资料 | `services/knowledge_bridge`（只读、Token、白名单） | 进入"无依据"分支，不给结论 |
| 四级最低实付报价 | `services/quote_engine` + 你自己的商业规则 JSON | 报价节点报缺口，只给方案不给价 |
| 产品图 / 海报 PNG | `services/poster_renderer`（需 Pillow）+ 生图 API | 排版节点阻断，不产出图片 |
| 图片内容审核 | Qwen3-VL-Plus（通义插件 + 百炼权限） | 视觉审核 NOT_RUN，成品不导出 |
| 容器内访问本机资料 | squid 桥接（`deploy/dify-local/`） | 容器拿到的是 403 |

逐项配置步骤、命令、验证方法和常见坑，全部写在 **[docs/HOW-TO-CONFIGURE.md](docs/HOW-TO-CONFIGURE.md)**。

---

## 四、五个画布

`apps/` 里已经放了 5 份**可直接导入的 DSL**，下载即用，不用先装 Python：

| 画布 | 文件 | 节点 / 连线 | 用途 | 跑起来需要 |
|---|---|---|---|---|
| 完整路由主应用 | `apps/full-workflow.candidate.yml` | **112 / 170** | 全链路：场景→策略→图文→核验→报价→讲解 | 路径 ③ 全部组件 |
| 产品介绍写审修订链 | `apps/product-intro-revise.candidate.yml` | 31 / 33 | 写作 → 独立审核 → 按意见修订，三跳闭环 | 两个文本模型 |
| 本地资料产品介绍最短链 | `apps/product-intro.candidate.yml` | 19 / 18 | 只走"查资料→写介绍"，最小可用链路 | 一个模型 + 知识桥接 |
| 平台策略分阶段模型联调 | `apps/stage-model.candidate.yml` | 16 / 19 | 验证不同阶段用不同模型的可行性 | 两个文本模型 |
| 合成图片视觉连通测试 | `apps/vision-probe.candidate.yml` | 5 / 4 | 只验证"图能不能被识别"，不含产品审核 | 通义视觉模型 |

建议按 **5 → 19 → 31 → 112** 的顺序导入，先确认单点通，再上全链路。每个画布的详细说明见 [apps/README.md](apps/README.md)。

---

## 五、这 5 份 DSL 是怎么来的

**两种用法都支持**：

- **直接用**：`apps/*.candidate.yml` 下载下来，在 Dify 里「导入 DSL 文件」即可
- **自己生成**：改了提示词之后，用生成器重新产出一份属于你自己的

```sh
python3 scripts/build_full_dify_bundle.py --out ./apps       # 112 节点主应用
python3 scripts/build_dify_bundle.py --out ./apps-intro      # 19 节点最短链
```

为什么还要留着生成器？因为**画布是产物，不是源文件**：

1. **单一来源**：`prompts/` 里的 11 份 System 原文才是源。想改提示词，改源再重新生成，避免"画布里的提示词"和"仓库里的提示词"两套不一致
2. **可审计**：生成器 `scripts/build_full_dify_bundle.py` 是可以读、可以测的代码，能验证画布里的每个节点是怎么被定义的
3. **可复现**：`manifest.json` 会记录节点数与来源文件 hash，画布和仓库版本能对上

所以：**想省事就下载，想改就生成。** 两条路产出的 DSL 是同一份。

---

## 六、诚实边界（必读）

- **133 条验收规格全部 NOT_RUN**（[docs/acceptance-cases.csv](docs/acceptance-cases.csv)）。导入成功 ≠ 应用可用。
- **真实模型调用成功过，但业务未通过。** 一次真实产品介绍运行中，`deepseek-flash` 写作 7.5 秒成功、`deepseek-v4-pro` 审核 98.6 秒成功，审核正确发现两段遗漏了全局配置限定，门禁 `gate=false`，业务被判不通过。这是设计意图（宁可拦下也不放过），但它意味着**没有一份"合格成稿"**。
- **P4 全部 20 份仍为空模板。** 141 条公开价格快照不能代替四级结算规则；本仓库不给真实最低实付。
- **离线测试通过不等于准确率。** `python3 -m unittest discover -s tests -v` 在有 Pillow 的环境下 157 项全过，但这是合成测试，不调用付费模型，不能推出"准确率 > 95%"。
- **插件装上不等于模型连通。** 认证插件 `langgenius/deepseek` 与 `langgenius/tongyi` 都已安装，但模型是否可用取决于你自己账号的余额与权限。

---

## 七、目录

| 路径 | 内容 |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | 20 分钟把画布跑起来 |
| [docs/HOW-TO-CONFIGURE.md](docs/HOW-TO-CONFIGURE.md) | 完整能力配置手册（逐项命令 + 验证） |
| [apps/README.md](apps/README.md) | 五个画布的用途与生成方式 |
| [docs/requirements-design.md](docs/requirements-design.md) | 需求与设计 |
| [docs/platform-workflow-build-guide.md](docs/platform-workflow-build-guide.md) | 节点搭建指南 |
| [docs/dify-prompt-binding-guide.md](docs/dify-prompt-binding-guide.md) | System 提示词绑定 |
| [docs/knowledge-source-modes.md](docs/knowledge-source-modes.md) | 本地资料 / ima 双模式 |
| [docs/local-knowledge-bridge.md](docs/local-knowledge-bridge.md) | 只读知识桥接 |
| [docs/multi-model-design.md](docs/multi-model-design.md) | 多模型接入 |
| [docs/quote-optimization-design.md](docs/quote-optimization-design.md) | 报价规则设计 |
| [docs/sales-demo-script-design.md](docs/sales-demo-script-design.md) | 三分钟对客讲解 |
| [docs/local-bridge-network-plan.md](docs/local-bridge-network-plan.md) | 容器 → 主机网络方案 |
| [docs/tooling-and-connectors.md](docs/tooling-and-connectors.md) | 工具与连接器 |
| [specs/business-tool-contract.md](specs/business-tool-contract.md) | 工具统一合同 |
| [specs/prompt-registry.json](specs/prompt-registry.json) | 提示词登记表 |
| [specs/model-routing.example.json](specs/model-routing.example.json) | 模型槽位配置样例 |
| [deploy/dify-local/README.md](deploy/dify-local/README.md) | 本机 Dify 部署（Lima 虚拟机） |
| `prompts/` | 11 份 System 提示词原文 |
| `tests/` | 离线测试 |

---

## 八、运行测试

```sh
python3 -m unittest discover -s tests -v
```

海报像素测试需要 Pillow，缺失时会明确跳过并标注，不算通过。测试不调用付费模型，不出公网。

## 九、边界与许可

- 本仓库不含用户知识库、原图、私有取证底稿、运行时 DSL 或任何凭证；使用者须自行取得合法数据访问权限。
- 不公开：凭证、共享库全文、源图集合、签名地址、私人路径、受控原始响应。
- 许可证：[Apache-2.0](LICENSE)。可商用、可修改、需保留版权与许可声明。
- 安全问题或数据边界问题请见 [SECURITY.md](SECURITY.md)，不要用公开 issue 提交任何客户资料、价格表或密钥。
