# 本机 Dify 到知识桥接的受控网络

2026-10-18。此文区分已执行探针与尚未应用的代理配置。业务服务仍遵循[本地桥接接口与授权边界](local-knowledge-bridge.md)。

## 已验证

在当前 Lima `huawei-dify` 虚拟机运行时，Mac 启动了仅监听 `127.0.0.1` 的随机端口 marker 服务。服务只返回随机测试字符串，不访问知识库、不接收凭证；验证后已关闭。使用既有 `busybox:latest` 镜像和 `--rm --pull never` 创建临时无挂载测试容器，未下载新镜像、未修改应用配置。

| 路径 | 实测结果 |
|---|---|
| Ubuntu guest → `192.168.5.2:<随机端口>` → Mac loopback | 成功，响应 marker 一致 |
| Ubuntu guest → `host.lima.internal:<随机端口>` | 成功，响应 marker 一致 |
| rootless Docker 默认 bridge 容器 → `192.168.5.2:<随机端口>` | 成功，响应 marker 一致 |
| 同容器 → `host.lima.internal:<随机端口>`，不加 hosts 映射 | 成功，响应 marker 一致 |
| 同容器 → 显式 `host.lima.internal:192.168.5.2` 映射 | 成功，响应 marker 一致 |

这些结果证明此刻的链路可达，不代表知识库认证、Dify HTTP 节点、模型节点或 SSRF 代理已经联调。没有用“主机名能解析”替代请求与响应证据。原始无凭证探针报告为本机 `research/bridge-network-probe.json`，该目录不进入公开交付。

[Lima 官方说明](https://lima-vm.io/docs/config/network/user/)解释了 `192.168.5.2` / `host.lima.internal` 到 Mac loopback 的映射；实际部署为 Lima 2.2.1，本报告以实测结果为准，不采用较新版本新增的配置项。

## 拟定路径与最小代理例外

```text
Dify HTTP 节点
  → ssrf_proxy:3128（Dify 既有代理）
  → http://192.168.5.2:8765/v1/<固定业务端点>
  → Mac 127.0.0.1:8765 knowledge_bridge
```

Dify 1.17.1 本机源码的 `docker/ssrf_proxy/squid.conf.template` 默认拒绝私网目的地址。因此默认代理下不会因为容器直连成功而自动工作。其 `SSRF_PROXY_ALLOW_PRIVATE_IPS` / `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` 入口仅按目的地址放行；配置整个宿主机地址会同时放开该地址的其他安全端口。本方案使用更窄的目的地址、端口、方法、路径联合条件。

审查用配置文件：[squid-bridge.conf.template](../deploy/dify-local/squid-bridge.conf.template)。**当前只是文件产物，尚未替换运行中配置。** 只允许 `192.168.5.2/32`、端口 `8765`、`POST`，且路径仅为当前已实现的 `/v1/contexts/resolve`、`/v1/kb/evidence`、`/v1/quotes/solve`。其他合同端点尚未实现，须开发并独立审查后再扩展 ACL，不能放开整个 `/v1/` 前缀。路径不能带 query 或 fragment，引用及凭证放在受控 Header / body。`CONNECT` 不可借此例外穿透；其他私网目的地址、其他宿主端口和其他路径继续命中私网拒绝。

候选生成器为 [generate-bridge-squid.py](../deploy/dify-local/generate-bridge-squid.py)，只接受已审查的 Dify 1.17.1 原模板或完全一致的已生成模板，遇到上游漂移即停止；它不读取环境变量、不接触 Docker/Lima。

已执行候选验证：5 项离线检查通过；使用既有 `ubuntu/squid:latest` 镜像，以 `--network none --pull never`、仅挂载无业务内容的临时候选配置运行 `squid -k parse`，退出码 0。解析保留了上游 IPv4/IPv6 重叠 ACL 提示，以及隔离网络下的主机名/rDNS 提示；未为消除提示擅自改公共策略。临时容器与临时配置已退出清理，实际应用仍未变更。语法成功不能代替动态允许/拒绝验证。

应用时只覆盖 `ssrf_proxy` 的 `/etc/squid/squid.conf.template` 只读挂载，不改 `agent_ssrf_proxy`，不改 Docker daemon、Mac 防火墙、公开监听端口或全局系统代理。此模板不包含上游生成的宽泛私网白名单 include，因此不能再叠加 `SSRF_PROXY_ALLOW_PRIVATE_IPS/DOMAINS` 扩大权限；如有新业务依赖，应另行审查目标端点。上游公共域名规则与 sandbox 桥接 include 保留。

工作流的 base URL 固定为 `http://192.168.5.2:8765`，不得用用户输入拼接 host、port 或任意路径。服务继续只绑定 Mac loopback，不能为方便联调改为 `0.0.0.0`。Dify 的基础设施仍能直连宿主其他地址，Squid 白名单不是容器整体网络隔离；应用必须避免向不可信节点提供任意网络执行能力，业务请求始终要求服务密钥和短期 proof。

## 联调与验收

1. 确认 Dify `ssrf_proxy` 启动。先运行默认策略 probe，保存访问 Mac marker 被拒绝的真实结果；不改配置前不能标成功。
2. 部署负责人审查并只对 `ssrf_proxy` 应用上述只读模板挂载，执行 Squid 配置语法检查；只重建该代理服务，保留数据卷与其他容器。
3. 启动实际知识桥接于 `127.0.0.1:8765`。无 Authorization 请求必须返回 401；携带仅本机私有配置的 Bearer 完成 `contexts/resolve → kb/evidence`。默认模型目的地未批准时应返回安全业务阻断，不为“连通成功”绕过数据外发白名单。
4. 通过同一代理验证允许的三条 POST 路径可达；错误方法、错误路径、错误端口、其他私网地址应仍被代理拒绝。失败、超时或未执行不得记为通过。
5. 在 Dify 真实 HTTP 节点验证上述两步，proof 只在下一 HTTP Header 中传递，避免进入模型、聊天内容或普通日志。核对 response 状态而非仅 HTTP 200，`ready` 才进入获准的下一节点。

探针复现：

```sh
python3 deploy/dify-local/probe-bridge-network.py --output research/bridge-network-probe.json
```

可在已有 SSRF 网络就绪后增加 `--ssrf-network <docker network 名称>`；脚本不会创建网络、修改策略或使用实际知识资料。随机端口 marker 在最小 `8765` 规则下被拒绝是预期结果，不能把随机端口 probe 用来证明固定业务端口已放行。固定端口的允许/拒绝与业务认证须单独联调。
