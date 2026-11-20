# Jane Street 协议模拟器 ASIC 竞赛要求

核对日期为 **2026-11-20**。Jane Street 于 2026-09-10 发布公告，最近一次标注更新为 **2026-11-09**，确认了 8×4 面积并补充了 FAQ。提交截止日为 **2027-01-18**，公告未列具体钟点或时区。以下是核心原文摘录和提交要求的中文摘要。[Jane Street 公告与 FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) · [Tiny Tapeout 赛事页](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/)

## 官方要求

> Your chip should be reprogrammable enough to support new protocols after fabrication, within its timing and I/O constraints.

作品须是开源、通用的协议模拟器 ASIC。用户应能在设计声明的引脚和时序范围内，为同一颗芯片编写新程序，实现设计时未预设的协议。架构由参赛者选择，可以采用指令引擎、eFPGA 或其他实现。[Jane Street 挑战说明与设计 FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/)

| 项目 | 提交时应满足的条件 |
| --- | --- |
| 工艺与面积 | 使用 Tiny Tapeout 的 IHP 130 nm CMOS5L Verilog 模板及流程。模板的 `main` 已面向 CMOS5L。按公告将 `info.yaml` 的 `tiles` 设为 `"8x4"`，每个设计最多 8×4 tiles。[官方模板](https://github.com/TinyTapeout/ttihp-verilog-template) · [赛事规则](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#the-rules) |
| 物理实现 | 提交版本须完成 Tiny Tapeout 流程并通过 precheck，公开仓库要能找到对应的 GDS 和通过记录。若触及 GitHub Actions 的 6 小时上限，可在本地跑该流程，再通过 Tiny Tapeout 的 custom GDS action 提交。[提交说明](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#what-to-submit) |
| 源码与软件 | 提交公开仓库链接，提供 RTL、测试、架构与指令集说明、汇编器或其他编程工具链（含适用的位流生成流程），以及所支持协议的示例程序。加载方式由设计者决定，需说明所用主机及加载步骤。[Jane Street 提交与设计 FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) |
| 验证说明 | 提交书面说明，解释验证方法及所用工具。使用 AI 工具时说明实际用法。验证工具由参赛者选择，评委很看重技术说明是否清晰、可读。[Jane Street 提交与评审 FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) |
| 板级接口 | 24 根数字 I/O 分为 8 入、8 出、8 双向，另有时钟和复位。设计须通过 `rst_n` 进入已知状态，取消选中会掉电，再次选中后需能重载。所需外接上拉、收发器或电平转换等要写入文档。工作频率自选，须在布局布线后满足所选协议的时序。[Tiny Tapeout 板级约束](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#pins-speed-and-the-board) |
| 参赛与入口 | 个人或团队均可，团队人数不限，每队一份作品，提交时仓库须公开。截至核对日，意向登记表用于接收更新；主办方表示稍后会在公告页发布最终提交表。目标批次为 2027 年 3 月，取决于代工厂排期。[Jane Street 公告及提交入口](https://blog.janestreet.com/protocol-emulator-asic-competition/) |

## 评委看什么

评审首先看**更换程序后能支持多大范围的新协议**，同时看实际演示、架构的独特能力、设计与验证方法及报告质量。官方没有固定评分权重或协议速度门槛。UART、SPI、I²C 是推荐起点；常见波特率、SPI 模式 0–3 和 I²C 100/400 kHz 是建议的演示工况。低速 USB、10 Mbit Ethernet 是挑战项。并行协议、同时支持控制器与目标角色可加分。门级仿真获强烈推荐，FPGA 原型和演示视频均可自选。[Jane Street 设计与评审 FAQ](https://blog.janestreet.com/protocol-emulator-asic-competition/) · [Tiny Tapeout 评审说明](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#how-entries-are-judged)

## 对 Protocol Chameleon 的优先级建议

以下判断基于 M10 的 RTL 提交 `5b99677`。**建议先让评委能从公开工具和示例复现“同一份 RTL，换程序实现新协议”，并为同一提交取得 GDS/precheck。** 我们产品规格里的 P1–P5 全部可编程、5 MHz SPI、1 MHz SWD 式换向和隐藏 DUT 盲测，是项目自己的验收目标。P2–P5 已有的自主检查与反馈可以用来展示架构特色；它们的全面通用化可以排在竞赛交付之后。[项目目标](../README.md#what-would-establish-success) · [官方评审依据](https://www.tinytapeout.com/competitions/jane-street-tt-protocol-emulator/#how-entries-are-judged)

| 优先级 | 仓库已有证据 | 接下来要补什么 |
| --- | --- | --- |
| 1 · 用程序实现新协议 | GPIO 引擎已能载入不同引脚程序，SPI 可以只换字节程序来改变事务格式。现有 UART 路径使用专用收发器；两份 SPI 示例都使用同一个 SPI 移位器。[GPIO 示例](info.md#two-program-images) · [SPI 示例](info.md#load-a-byte-transaction-program) | 选一个能区分协议能力的例子，例如由通用引擎执行的 I²C 事务或新定义的时钟协议。固定 RTL，让他人只替换程序即可复现，并用独立对端检查波形、应答和时序。 |
| 2 · 让他人能写并运行程序 | 已有指令编码、十六进制程序、引脚加载说明及 cocotb 加载代码。M10 的验证记录列出 45 项通过的顶层测试。[编程接口](info.md#instructions) · [加载测试](../test/test_byte_program.py) · [验证记录](../test/README.md) | 把编程工具链和可编辑示例整理成评委可直接运行的入口，给出从源程序到加载、验证的命令。汇总验证方法、覆盖范围和 AI 的实际用途。 |
| 3 · 交付同一版本的物理结果 | `tiles` 已设为 `8x4`，仓库含 Apache-2.0 许可证。M8 评估副本补了元数据后通过 GDS 流程和全部 10 项 precheck。M10 现有报告只列出综合及布局前时序。[项目配置](../info.yaml) · [许可证](../LICENSE) · [物理验证记录](../test/README.md#m8-physical-feasibility) | 尽早补齐 `title`、`author`、`description` 并做物理回归。选定参赛提交后，在公开仓库关联该版本的 RTL、测试、GDS、precheck 和报告，再通过正式表单提交。 |
