# QUICKSTART · 20 分钟把画布跑起来

目标：在你自己的 Dify 里打开那个 112 节点的画布，并成功跑一轮对话。

**你会得到**：一个能对话、能按模板产出营销文本的应用。
**你不会得到**：真实报价、产品图、海报（那些要按 [docs/HOW-TO-CONFIGURE.md](docs/HOW-TO-CONFIGURE.md) 逐项配）。

---

## 第 0 步 · 确认版本

| 项 | 要求 | 怎么确认 |
|---|---|---|
| Dify | **1.17.x**（作者验证于 1.17.1，commit `8387590`） | 页面右下角或「设置 → 关于」 |
| Python（仅用于生成画布） | 3.10+，只用标准库 | `python3 -V` |
| 磁盘 | 至少 10 GB 空闲 | Dify 镜像约 2.5 GB 压缩 / 解压后更大 |

> Dify 版本不对是导入失败的头号原因。1.17 之后的版本改过若干节点 DTO，导入可能报"节点类型不支持"。

**装 Dify 的两个选择：**

- **省事**：用 Dify 官方的 Docker Compose（`git clone` 官方仓库 → 切到 1.17.1 标签 → `docker compose up -d`）
- **不想装 Docker**：用 Dify Cloud。**但要注意**云端版本通常更新，导入后需逐节点核对有没有节点丢失

本仓库另外提供了一套"不污染全局 Docker"的本机方案（Lima 虚拟机上跑 rootless Docker），见 [deploy/dify-local/README.md](deploy/dify-local/README.md)。适合 macOS 且不想装 Docker Desktop 的人，代价是多花 20–30 分钟。

---

## 第 1 步 · 拿到画布 DSL

**最省事**：直接用仓库里现成的 5 份，在 `apps/` 目录下，选你要的下载即可。

| 文件 | 节点 | 适合 |
|---|---|---|
| `apps/vision-probe.candidate.yml` | 5 | 先验证视觉通路 |
| `apps/product-intro.candidate.yml` | 19 | 最短链，最容易跑通 |
| `apps/stage-model.candidate.yml` | 16 | 分阶段模型实验 |
| `apps/product-intro-revise.candidate.yml` | 31 | 写作→审核→修订闭环 |
| `apps/full-workflow.candidate.yml` | **112** | 全链路主应用 |

**想自己生成**（改过提示词之后应该这样做）：

```sh
cd <本仓库根目录>
python3 scripts/build_full_dify_bundle.py --out ./apps-gen
```

预期产出 `apps-gen/full-workflow.candidate.yml`（112 节点）、`manifest.json`（生成记录：节点数、来源 hash）、`prompts/`（本次用到的提示词快照）。

**验证**：导入后看 `manifest.json` 里节点数是 112、连线 170；直接下载的那份可用本文的节点数对照。

---

## 第 2 步 · 导入 Dify

1. 打开 Dify 工作室 →「创建空白应用」下拉 → **导入 DSL 文件**
2. 选 `apps/full-workflow.candidate.yml`
3. 导入后会生成一个新应用，画布上应有 112 个节点

**验证**：画布能完整渲染、能拖动缩放、节点没有大红色报错块。

---

## 第 3 步 · 装模型插件

画布里的 14 个 LLM 节点都用 **DeepSeek**（provider `langgenius/deepseek`）。DSL 的 `dependencies` 是空的，**插件不会被自动装**，必须手动来：

1. 「设置 → 插件」→ 搜索 `deepseek` → 安装 **`langgenius/deepseek`**
2. 装 **`langgenius/tongyi`**（可选，只有做图/审图才需要）
3. 回到「设置 → 模型供应商」→ 填你的 **DeepSeek API Key**

作者验证过的插件版本：`langgenius/deepseek` **0.0.24**、`langgenius/tongyi` **0.2.23**。版本差太远时模型名可能对不上。

---

## 第 4 步 · 核对模型名（最容易卡住的一步）

DSL 里写死的模型名是作者环境里的实际名字：

| 槽位 | DSL 里的名字 | 你环境里可能是 |
|---|---|---|
| 写作 / 策略 / 文案 | `deepseek-flash` | `deepseek-chat` |
| 独立审核 | `deepseek-v4-pro` | `deepseek-reasoner` |

**这两个名字不是 DeepSeek 官方的固定 ID**，是作者环境里插件声明的名字。不同插件版本、不同接入方式（官方 / 中转）会不一样。

做法：画布上双击任意 **LLM 节点** → 看「模型」下拉里有没有 `deepseek-flash`。
- 有 → 直接跑
- 没有 → 全选 14 个 LLM 节点，逐个改成你下拉里实际存在的模型；**但写作和审核必须是两个不同的模型**，否则独立审核这道门禁失去意义

---

## 第 5 步 · 跑第一轮

在主应用对话框输入一句真实需求，例如：

```
帮大学新生选一台 MateBook，预算 6000 左右，要写一篇小红书文案
```

**预期结果（重要）**：它大概率**不会**给你一份完整成稿，而会在某个节点明确阻断，并在回答里说明缺什么。这是设计如此——缺报价规则、缺知识源、缺图片时它宁可停下，也不编。

看到阻断 = 链路是通的。你接下来要做的不是"修 bug"，而是按 [docs/HOW-TO-CONFIGURE.md](docs/HOW-TO-CONFIGURE.md) 把你需要的那个能力补上。

---

## 排错对照表

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 导入报"节点类型不支持 / 未知节点" | Dify 版本不匹配 | 换 1.17.x |
| LLM 节点标红、跑起来报模型不存在 | 插件没装或模型名不对 | 回第 3、4 步 |
| 审核节点永远拦下 | 写作与审核配成了同一个模型 | 换成两个不同模型 |
| `SOURCE_PATH_REJECTED` / 403 | 知识桥接没起，或路径不在白名单 | 见配置手册第 4 节 |
| `AUTH_REQUIRED` / 401 | 桥接缺 `HUAWEI_TOOL_TOKEN` | 同上 |
| 报价节点说缺规则 | 没提供商业规则 JSON | 见配置手册第 5 节 |
| 海报节点不产出 | 没装 Pillow 或没配生图 | 见配置手册第 6 节 |
| 容器里访问 `127.0.0.1` 失败 | 容器里的 127.0.0.1 是容器自己 | 见配置手册第 4.4 节（squid 桥接） |

---

## 下一步

- 想补齐真实能力 → [docs/HOW-TO-CONFIGURE.md](docs/HOW-TO-CONFIGURE.md)
- 想懂每个节点为什么这么搭 → [docs/platform-workflow-build-guide.md](docs/platform-workflow-build-guide.md)
- 想改提示词 → 改 `prompts/` 里的原文，再重新生成 DSL，别直接改画布
- 想知道哪些能力其实还没验收 → [docs/acceptance-cases.csv](docs/acceptance-cases.csv)
