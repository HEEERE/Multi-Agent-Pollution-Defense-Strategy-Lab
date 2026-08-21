# Phase 1～4 核心运行实现报告

**日期：** 2026-08-21
**方案依据：**《最终方案-v4-不对称重构版.md》
**状态：** 核心运行路径已实现并通过回归测试

## 1. 本次交付范围

本次工作将 v4 方案中原先只存在于设计文档或 `research/scale` 离线原型中的核心机制，落到可被运行时调用的 Python 模块，并接入现有 `MessageBus` 和实验运行器。

本次完成的是 Phase 1～4 的核心运行基础设施，不包含 Phase 5～6 的完整论文实验、外部基线复现和形式证明附录。

## 2. 总体运行链路

```text
Agent / Simulation
        |
        v
MessageBus
  |             \
  |              +--> ActionGateway --> DeterministicPolicy
  |                                      |
  +--> ProvenanceLedger <----------------+
        |
        +--> ArtifactVersion / Derivation / StateTransition
        |
        +--> conservative projection (P1, veto)
        +--> tight projection (P0, propose)
        |
        +--> StateController --> ResidualChecker --> CertificateChecker
```

关键原则：

- 事件只有在提交前置检查通过后才进入持久化、广播和下游 handler。
- Artifact 是不可变版本；当前状态只能由 `state_transitions` 的最新记录派生。
- tight graph 只能提出保留候选，不能签发安全结论。
- conservative graph 承担可达性、残余污染和证书校验。
- `UNKNOWN`、snapshot 变化、handler 异常和 dry-run 外部动作均不能被当作 allow。

## 3. Phase 1：版本化 ProvenanceLedger

### 3.1 新增模块

- `backend/app/provenance/models.py`
- `backend/app/provenance/ledger.py`
- `backend/app/provenance/__init__.py`

### 3.2 已实现数据模型

| 模型 | 作用 |
|---|---|
| `ArtifactVersion` | 不可变实体版本，包含 kind、value hash、完整性、机密性、来源主体和 taint class |
| `Derivation` | 记录 child 与 parent 版本、activity 和关系类型 |
| `StateTransition` | 追加式状态转换，支持 active/quarantined/invalidated/recovered/retained |
| `ProvenanceSnapshot` | 绑定 ledger seq、state seq、policy version、component versions 的快照 |

### 3.3 账本约束

- `artifact_versions` 不允许就地修改。
- `state_transitions` 为状态唯一写入路径。
- 新 Artifact 提交时自动追加初始 `ACTIVE` 状态转换。
- 每次 Artifact、relation 或 state transition 都推进序列号。
- `snapshot_hash = SHA-256(ledger_seq, state_seq, policy_version, component_versions)`。
- Gateway 执行 handler 后重新验证 snapshot；期间发生账本变化则返回 `UNKNOWN/snapshot_changed`。

## 4. Phase 2：运行上下文与异构状态

### 4.1 RunRuntime

新增 [backend/app/runtime.py](../backend/app/runtime.py)：

- `RunManifest`
- `RunContext`
- `RunEngine`

每个 run 单独创建 ledger、gateway、action boundary lock 和组件配置，Manifest 支持：

- seed
- policy version
- component versions
- provenance mode
- horizon closure
- model role assignment

`RunEngine.at_action_boundary()` 通过 per-run lock 串行化动作边界。

### 4.2 版本化 Memory/RAG

新增：

- `backend/app/entities/versioned.py`
- `backend/app/entities/memory.py`
- `backend/app/entities/rag.py`

`VersionedMemory` 和 `VersionedRAG` 的每次写入都会生成新版本；父版本通过 `Derivation` 记录。读取只返回当前状态不是 `QUARANTINED` 或 `INVALIDATED` 的版本，因此隔离后的版本不会继续进入检索结果。

### 4.3 MessageBus 接入

`MessageBus` 新增：

- `bind_provenance_ledger()`
- `bind_action_gateway()`
- `_record_provenance()`

绑定账本后，每个已提交事件会自动生成：

- `event_<event_id>` ArtifactVersion
- 从 `parent_event_id` 推导出的 `derived_from` relation
- BLOCK/QUARANTINE/ISOLATE 对应的状态转换

实验运行器会为每次运行绑定独立的 `run_id`（即使复用进程级 MessageBus 也不会复用旧运行状态）；兼容旧的 FakeStore 时自动回退到内存账本。

### 4.4 Provenance 投影 API

新增 [backend/app/api/routes/provenance.py](../backend/app/api/routes/provenance.py)：

```text
GET /api/v1/provenance/{run_id}?mode=conservative
GET /api/v1/provenance/{run_id}?mode=tight
```

API 返回 snapshot hash、节点和关系。投影层会过滤 `QUARANTINED` 与 `INVALIDATED` 版本，保留版本按标签脱敏；HTTP provenance、运行事件和两个 WebSocket 广播路径共用同一状态投影，避免公开传输绕过标签。

## 5. Phase 3：ActionGateway 与确定性授权

### 5.1 新增模块

- `backend/app/actions/models.py`
- `backend/app/actions/policy.py`
- `backend/app/actions/gateway.py`
- `backend/app/actions/__init__.py`

### 5.2 ActionRequest

`ActionRequest` 包含：

- action id、run id、actor agent、tool、operation
- 参数及其 artifact refs、semantic role、integrity
- capability requested
- resource scope
- effect class
- idempotency key
- reversible
- deadline

### 5.3 Effect 与失败语义

| Effect | 语义 | 当前 Gateway 行为 |
|---|---|---|
| E0 | 纯读/格式化 | 可在确定性策略通过后执行 |
| E1 | 内部可版本化写入 | 检查 provenance 和状态 |
| E2 | 外部可逆动作 | `dry_run` 下拒绝；live 下需通过策略 |
| E3 | 外部不可逆动作 | `dry_run` 下硬拒；低完整性参数拒绝 |

`effect_mode` 在 Gateway 构造时确定，运行中没有可变 setter。`dry_run` 会在查找/调用 adapter 之前拒绝 E2/E3。

### 5.4 确定性授权

`DeterministicPolicy` 是当前唯一能够返回 `ALLOW` 的策略组件，检查：

- deadline 是否过期
- capability 是否越权
- resource scope 是否越权
- 引用 Artifact 是否 quarantined/invalidated
- provenance 是否未知
- retained 标签是否试图进入 E2/E3（明确禁止）
- 参数或祖先是否包含 low-integrity 来源
- E3 参数完整性是否为 high

LLM、detector 和模型类证据不会获得 allow 权限。

### 5.5 MessageBus 兼容接入

旧事件生产者仍可发布普通事件；当事件带有 `effect_class`、`capabilities`、`artifact_refs` 等元数据时，MessageBus 会转成 `ActionRequest`，先执行 Gateway 授权，再决定是否持久化和投递。拒绝事件不会进入目标 handler。

## 6. Phase 4：双图、StateController 与证书

### 6.1 双图投影

新增：

- `backend/app/provenance/projection.py`
- `backend/app/provenance/conservative_builder.py`
- `backend/app/provenance/tight_builder.py`

`build_conservative()` 会在显式 derivation 之外合并可见输入，形成 P1 过近似；`build_tight()` 只保留结构化的 P0 relation、support relation 和 authorized relation。

### 6.2 StateController

新增 [backend/app/state/controller.py](../backend/app/state/controller.py)，负责：

- 同一 run 上构造 conservative/tight graph
- 计算 sink reachability
- 沿祖先闭包传播污染
- 输出 clean / contaminated_reachable / contaminated_unreachable
- 追加状态转换
- 执行 propose/veto retention
- post-state residual recheck
- action boundary 后将重新可达的 retained 版本转为 invalidated
- 状态机前置条件和终态约束（invalidated 版本不可重新 active）

### 6.3 Retention 规则

```text
proposed = tight graph 提出的候选
vetoed   = conservative graph 中仍可达 protected sink 的候选
retained = proposed - vetoed
```

只有 conservative checker 返回 `COVERED + exhaustive` 时才允许写入 `RETAINED`。post-state 复验发现残余污染时，会将候选写回 `INVALIDATED`，不返回有效 retention 结果。

### 6.4 独立 checker 与证书

新增：

- `backend/app/verification/residual_checker.py`
- `backend/app/verification/certificate_checker.py`

checker 不依赖 solver；证书绑定：

- run id
- snapshot hash
- sink scope
- blocked versions
- completeness

证书有效条件：

```text
status == COVERED
AND completeness == EXHAUSTIVE
AND 当前 snapshot hash == 证书 snapshot hash
```

预算耗尽或 sink 不在当前图中返回 `UNKNOWN`，不能签发安全证书；求解器明确证明 `Break(W)=∅` 时返回独立的 `UNSATISFIABLE`，两者不能混同。

## 7. 测试与验证

新增测试：

- `backend/tests/test_phase14_runtime.py`
- `backend/tests/test_provenance_bus.py`
- `backend/tests/test_versioned_entities.py`

覆盖内容：

- append-only artifact/state transition
- snapshot hash 在状态变化后失效
- P0/P1 双图差异
- Gateway dry-run E2/E3 硬拒
- 低完整性祖先传播拒绝
- MessageBus 事件版本化和关系绑定
- QUARANTINE 状态转换
- certificate snapshot 失效
- retained propose/veto 和状态写入
- 版本化 Memory/RAG 隔离读取

最终验证结果：

```text
backend/.venv/Scripts/python.exe -m pytest backend/tests -q -p no:cacheprovider
346 passed, 1 skipped

python -m compileall -q backend/app
通过

frontend: npm run typecheck
通过
```

## 8. 范围边界

以下内容属于被明确排除的 Phase 5～6 研究交付，不在本轮实现范围内：

1. 完整 M/E/X benchmark、15 类攻击矩阵和规模预实验结果。
2. AgentDojo/A2ASecBench 等外部基线复现。
3. 预注册统计、论文 Go/No-Go 判定和形式证明附录。
4. 面向论文实验规模的异步 repository 与数据库部署优化。

因此，本报告的“完成”指 Phase 0～4 的运行机制和已知实现缺陷已经收敛并通过当前测试集；不等同于 Phase 5～6 的论文实验已经完成。
