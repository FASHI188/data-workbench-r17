# 投资项目接续规则 V3.3

这是投资项目跨对话接续的稳定规则层，只规定恢复顺序、权威层级、Checkpoint、上下文预算、聊天生命周期与收尾规则；不得写入会频繁变化的SHA、PR、阶段数字、Actions结果或当前任务进度。

## 新对话恢复顺序
1. 先读Airtable《执行检查点》。只有最新状态为RUNNING/BLOCKED时，恢复当前任务、已完成步骤、阻塞和下一步唯一动作；若最新检查点为DONE，不展开旧DONE正文。
2. 读Airtable《接续快照》CURRENT。
3. 实时核GitHub integration及CURRENT/Checkpoint明确指向的相关PR、Actions、Artifact；不得无目的扫描大量历史PR/分支。
4. 读仓库START_HERE.md。
5. 读governance/project_module_index.json恢复模块地图；只在当前任务需要时展开对应evidence。
6. 读governance/accepted_project_state.json恢复仓库已接受业务进度；live integration SHA必须运行时读取GitHub，不得自引用。
7. 只读取与当前模块/用户点名别名直接相关的ACTIVE长期决策，不批量展开全部完整决策。
8. 维护日志、旧交易员聊天、历史项目来源只在冲突、追溯、复盘或用户明确要求时按需读取；不得作为新对话启动包。

新“交易员X”对话不从头重讲框架。若用户只新建对话，恢复后只说明“当前做到哪、下一步是什么”；若用户说继续/开始/开干/执行，完成最小实时核验后直接从下一步继续。

## 上下文预算 / 防两句话满对话
1. 新对话默认使用“最小状态包”：最新RUNNING/BLOCKED Checkpoint（如有）+ CURRENT + live integration/active PR事实 + accepted state + 当前模块索引。
2. 禁止把上一交易员长摘要、完整维护日志、全部历史PR、全部长期决策、全部项目来源整包复制进新对话。
3. 旧交易员聊天属于检索线索/历史归档，不是启动依赖。能由GitHub/Airtable确认的状态，禁止再从聊天历史重复装载。
4. 历史证据按需读取：用户问到具体旧模块、冲突、根因或审计时，才读取对应最小证据集合，回答后不把整份历史继续滚入后续状态摘要。
5. 长任务的进度必须持续外置到Checkpoint/CURRENT/GitHub，而不是依赖当前聊天上下文保存。
6. 维护日志保持追加式审计，但新对话不得例行读取“最新10条”；只有最后日志指针异常、冲突或追溯时才读取相关日志。
7. 回复默认只携带当前任务所需事实，不反复复述已冻结框架、旧版本链和已完成阶段。
8. 无法读取精确剩余上下文容量时，不得伪称知道“还剩多少”；通过最小启动包和及时外置进度降低对话过早耗尽风险。

目标：对话窗口只是操作界面，不是项目状态存储。即使平台自动提供部分项目记忆，代理自身也不得主动扩大为全历史上下文。

## 聊天生命周期 / 两活一归档
1. 默认只保留“当前交易员 + 上一交易员”作为活跃聊天保险层；更老交易员应归档而不是继续作为活跃工作窗口。
2. 新交易员创建后，必须先按本规则从Airtable/GitHub恢复并核对：当前模块、当前任务、live integration、相关active PR/HEAD、权限边界和下一步唯一动作。只有核对成功后，才允许归档“上上个交易员”及更早聊天。
3. 归档是聊天生命周期管理，不是项目状态迁移。归档前不得要求把旧聊天全文、长摘要或完整历史重新复制到CURRENT/Checkpoint。
4. 正常继续工作不得依赖取消归档旧聊天；只有用户明确追溯历史、冲突调查或审计时，才按需打开对应旧聊天/日志。
5. 如果新交易员恢复结果与GitHub/Airtable冲突，则停止归档动作并标记“接续异常/证据不足”，先解决冲突。
6. 不自动删除历史聊天；聊天删除不是本治理默认动作。
7. 实际ChatGPT归档UI若无可用连接器，由用户手动完成；代理必须先给出明确的“应保留/应归档”范围，不得假装已替用户完成UI归档。

## 冲突裁决
用户最新明确指令 > 项目级指令与本规则 > GitHub live技术事实 > 最新RUNNING/BLOCKED Checkpoint > CURRENT快照 > accepted_project_state + Module Index > ACTIVE长期决策 > 当前待办/维护日志 > 历史项目来源/旧README > 聊天记忆。

无法消解时写“接续异常/证据不足”，不得猜测继续。GitHub live回答“技术上现在是什么”；Checkpoint回答“正在干什么、下一步是什么”。

## Checkpoint
任何长任务、多步骤任务、GitHub/Airtable治理任务开始时必须创建RUNNING Checkpoint。完成重要步骤、分支/HEAD/PR变化、Actions/Artifact出结果、出现阻塞、下一步变化、权限边界变化后必须立即更新，不等最终回复。完成改DONE，真实阻塞改BLOCKED；历史保留不删。

目标：旧对话突然满时，最多丢当前一个尚未验证的小步骤，不能丢整条任务链。

## Module Index
重要模块新增、改名、生命周期/依赖/验收状态变化时同步更新project_module_index.json。用户问“哪个模块、做到哪、还差什么、旧名字是什么”时先查索引，再按evidence/decision读取必要证据，不靠聊天记忆逐个翻。

## 长期决策
长期架构、产品路线、模型边界、治理原则进入Airtable《长期决策》。历史不删除；被替代标SUPERSEDED。长期决策表示设计与边界，不等于已实现、已验收或已授权。

## 稳定规则与动态状态分离
本文件与START_HERE不得硬编码当前SHA、PR、阶段、freshness日期、Actions结果或当前任务。冻结Stage2/Stage3 manifest只证明其历史范围，不是整个项目当前状态。旧README动态文字不得覆盖GitHub live、Checkpoint、CURRENT或START_HERE。

## 收尾
任务结束前：实时回读GitHub → 必要时更新Module Index/accepted state → Checkpoint改DONE/BLOCKED → 更新CURRENT → 更新当前状态/待办 → 必要时版本化长期决策 → 写维护日志并更新指针 → 回读一致性。任一步失败必须写“收尾未完整”。

## 跨项目误发
用户明确说发错项目/作废/清除后，该段内容禁止进入投资项目Checkpoint、CURRENT、待办、长期决策、代码、数据和后续接续。若已进入持久层，只清明确污染，不误删正常历史。

## 权限
接续只恢复状态，不自动升级训练、OOS、lockbox、实盘或main合并权限；这些继续由当前业务gate和用户授权单独决定。

稳定关系：规则文件=接续宪法；START_HERE=启动入口；Checkpoint=进行时现场；CURRENT=快速摘要；Module Index=全模块地图；accepted state=仓库已接受进度；长期决策=长期架构；维护日志=历史审计；旧交易员聊天=按需检索的历史线索。