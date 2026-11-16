# 本机 Dify 部署

目标：这台Apple Silicon Mac上的单用户开发环境。版本锁定Dify 1.17.1（官方commit `8387590ace4a094de812b7847fc6a4c3a27cd52b`），容器运行于项目独立的Lima 2.2.1 Linux虚拟机；没有安装全局Docker Desktop、改系统登录项或开放公网。

当前状态（2026-10-18）：平台已安装运行，12个默认镜像已下载、14个持久服务运行，管理员初始化完成并已登录工作室，开发应用已导入。实际Redis PING、Celery worker回复和初始化HTTP检查均通过。DeepSeek两个文本模型及Qwen3-VL-Plus合成图片测试已真实调用成功；产品介绍首轮因缺少配置限定被独立审核阻断，完整主应用仍未验收。详细记录见[部署状态](../../docs/dify-local-deployment.md)、本机状态（本地记录或生成材料，未随公开源码发布）和模型连接记录（本地记录或生成材料，未随公开源码发布）。

## 文件与数据

- 官方上游：项目 `.local/dify/upstream`，只稀疏检出docker目录，保留release信息。
- 本机运行时：`.local/toolchain`；已核验官方SHA256，再解包安装。
- 虚拟机：`.local/lima/huawei-dify`；数据写入此VM磁盘，不能删除后声称保留了业务资料。
- 本机源配置：`.local/dify/upstream/docker/.env`，权限0600，含随机基础服务密钥；不入Git、不回显。
- 实际guest目录：`~/dify-docker`。首次复制后guest `.env`和volumes是运行状态；修改本机源配置不会自动覆盖运行配置或数据库。

VM只挂载本项目Dify上游docker目录，只读，不共享整个用户主目录。平台源码/配置从该只读挂载复制到guest自己的目录后运行，数据库与文件位于guest卷。DeepSeek与通义凭证已由用户在Dify原生配置页保存，界面各显示1份API Key配置；ima尚未配置。本文和状态记录均不包含凭证、用户知识库或原图。

官方Dify认证插件`langgenius/deepseek` 0.0.24、`langgenius/tongyi` 0.2.23已安装。DeepSeek此前余额不足，用户充值后已恢复；当前成功推理记录取代早期余额阻断状态，历史错误仍保留。

## 本机资源边界

已测8GiB内存、初始约12.6GiB可用磁盘。首次采用4GiB Linux guest、4 vCPU及1个Celery Worker进行单用户开发试运行；低于Dify官方macOS建议的8GiB VM配置，不能由此声称满足正式并发或可靠性验收。官方全局最低硬件与Mac VM建议口径分开记录。

镜像arm64元数据已核验，压缩去重约2.453GiB；解包、guest系统、插件和数据库另占空间，不能把压缩体积当安装实占。首次安装使用5GiB主机磁盘保留线，触线停止任务VM并报告，不清理用户资料。该保留线是本项目安装保护策略，不是Dify官方硬盘规格。

## 运行命令

在项目根目录执行：

```sh
python3 deploy/dify-local/preflight.py --install
./deploy/dify-local/dify-local.sh resume-install
./deploy/dify-local/dify-local.sh status
./deploy/dify-local/dify-local.sh verify-runtime
./deploy/dify-local/dify-local.sh start
./deploy/dify-local/dify-local.sh stop
```

`resume-install`用于已准备guest后的镜像拉取与启动，先检查已有准备的续装余量（19.5GiB，全新安装建议20GiB）并启用临时5GiB保护；执行成功仍需HTTP/健康核验。`start/stop`用于首次部署成功之后的运行控制；首次guest准备尚未完成时不要把命令执行失败当成已经装好。`stop`保留容器和数据；本脚本没有删除volume或虚拟机操作。

`verify-runtime`执行只读运行探测（本地记录或生成材料，未随公开源码发布）：验证api、worker、worker_beat的broker密码与Redis配置一致且指向本地redis，再实际发Redis PING和有界Celery worker PING，最后检查初始化HTTP接口。该命令不调用模型、不回显密钥。当前已修复broker URL与原Redis密码不一致的问题，保留原密码，仅同步并URL编码后重建相关服务；实际探测Redis PING=true、Celery回复1、HTTP`step=finished`全部通过。

当前工作室地址为 `http://localhost:8080/apps`，首页为 `http://localhost:8080`。HTTP页面和初始化API已验证，初始化API的`step=finished`；无须再次访问`/install`创建管理员。主机仅开放loopback映射：`127.0.0.1:8080`、`127.0.0.1:8443`及`127.0.0.1:15003`；HTTPS证书尚未验收。管理员密码和模型密钥由用户在本机相应页面输入，不发送到聊天。

## 验证范围

已验证：VM运行、Docker/Compose版本、Compose配置、关键容器健康、Redis认证与Celery控制回复、初始化HTTP、loopback端口、管理员登录、画布导入及本轮实际模型调用。尚未验证重启后的业务数据恢复、并发可靠性或完整业务交付；平台与单节点成功不能证明最优报价或准确率大于95%。

本地知识桥接的真实“API容器→SSRF代理→Mac”测试已通过，GET和未获准路径被403拒绝，见传输测试记录（本地记录或生成材料，未随公开源码发布）。桥接只绑定Mac的`127.0.0.1:8765`，经Lima主机地址接受指定POST入口；未授权模型不外发事实。产品介绍的范围HTTP与Code节点已实际运行，当前文本模型许可已用于真实写作/审核联调，不能再把早期白名单为空的负向测试当作当前配置。

真实产品介绍运行`b6b6a550-df7f-475d-9f30-1ea7eb855e01`：`deepseek-flash`写作成功7.504104秒，`deepseek-v4-pro`审核成功98.621833秒；审核正确发现两段遗漏全局配置限定，gate=false，业务未通过。Qwen3-VL-Plus另在应用`3ae2514a-cac6-43a5-baa8-1db57e2407a5`对自生成单图识别红圆、蓝矩形、绿三角和`K7M4`，问题未给出标准答案；只证明该合成样例的File输入与识别，不是产品审核或生成验收。

`qwen-image-3.0-pro`仍只有离线适配器，未真实调用；ima元数据适配器34项离线测试通过，但凭证、原文读取与bridge接入均未完成。P4仍为空模板，报价接口继续明确阻断；真实四级方案、主应用视觉审核和完整交付仍待验收。

Dify上游默认服务与SSRF代理/沙箱隔离保留；仅关闭可选协作模式，未通过删除安全服务来瘦身。插件调试端口使用数值环境变量与loopback Compose覆盖文件分别配置，避免把地址串传入API要求数值的端口字段。模型依然可能远端调用，本地平台不等于本地模型；外发授权、账号可用模型及调用费用记录须在实际配置时核验。

## 来源

[Dify官方Compose部署](https://docs.dify.ai/en/self-host/deploy/quick-start/docker-compose)、[Dify 1.17.1](https://github.com/langgenius/dify/releases/tag/1.17.1)、[Lima官方安装](https://lima-vm.io/docs/installation/)。资源和初次运行日志保存在本机research工作底稿，不公开凭证或P4原文。

续装说明（2026-10-18）：用户补足空间后实测19.82GiB，已有VM独立磁盘/运行时和部分镜像层，续装预检使用19.5GiB；全新安装仍建议20GiB。安装期间5GiB自动停机保护策略不变；日常`start`不会自动启动该保护进程。这是针对本次已有准备的工程判断，非Dify官方规格。
