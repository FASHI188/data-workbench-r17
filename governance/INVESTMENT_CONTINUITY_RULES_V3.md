# 投资项目接续规则 V3

这是投资项目跨对话接续的稳定规则层，只规定恢复顺序、权威层级、Checkpoint与收尾规则；不得写入会频繁变化的SHA、PR、阶段数字、Actions结果或当前任务进度。

## 新对话恢复顺序
1. 先读Airtable《执行检查点》。最新状态为RUNNING/BLOCKED时，恢复当前任务、已完成步骤、阻塞和下一步唯一动作。
2. 读Airtable《接续快照》CURRENT。
3. 实时核GitHub integration、相关分支、HEAD、PR、Actions/Artifact；不得从旧聊天猜当前技术状态。
4. 读仓库START_HERE.md。
5. 读governance/project_module_index.json恢复全模块地图。
6. 读governance/accepted_project_state.json恢复仓库已接受业务进度；live integration SHA必须运行时读取GitHub，不得自引用。
7. 读Airtable全部ACTIVE长期决策索引；用户命中模块/别名时再读完整决策。
8. 只有冲突、追溯、复盘时才查维护日志；日志不是进行时第一入口。

新“交易员X”对话不从头重讲框架。若用户只新建对话，恢复后直接说明“当前做到哪、下一步是什么”；若用户说继续/开始/开干/执行，完成实时核验后直接从下一步继续。

## 冲突裁决
用户最新明确指令 > 项目级指令与本规则 > GitHub live技术事实 > 最新RUNNING/BLOCKED Checkpoint > CURRENT快照 > accepted_project_state + Module Index > ACTIVE长期决策 > 当前待办/维护日志 > 历史项目来源/旧README > 聊天记忆。

无法消解时写“接续异常/证据不足”，不得猜测继续。GitHub live回答“技术上现在是什么”；Checkpoint回答“正在干什么、下一步是什么”。

## Checkpoint
任何长任务、多步骤任务、GitHub/Airtable治理任务开始时必须创建RUNNING Checkpoint。完成重要步骤、分支/HEAD/PR变化、Actions/Artifact出结果、出现阻塞、下一步变化、权限边界变化后必须立即更新，不等最终回复。完成改DONE，真实阻塞改BLOCKED；历史保留不删。

目标：旧对话突然满时，最多丢当前一个尚未验证的小步骤，不能丢整条任务链。

## Module Index
重要模块新增、改名、生命周期/依赖/验收状态变化时同步更新project_module_index.json。用户问“哪个模块、做到哪、还差什么、旧名字是什么”时先查索引，再按evidence/decision读取证据，不靠聊天记忆逐个翻。

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

稳定关系：规则文件=接续宪法；START_HERE=启动入口；Checkpoint=进行时现场；CURRENT=快速摘要；Module Index=全模块地图；accepted state=仓库已接受进度；长期决策=长期架构；维护日志=历史审计。
