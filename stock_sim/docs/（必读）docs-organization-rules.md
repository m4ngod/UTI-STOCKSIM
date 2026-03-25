# UTI-STOCKSIM docs 目录整理规则

_生成时间：2026-03-22 17:09 (Asia/Shanghai)_

本文档用于规范 `docs/` 目录下文档的层级、分类、命名与放置原则，防止文档持续堆积在同一层级，导致后续查阅、续接、治理和归档成本不断上升。

---

# 1. 目标

本规则的目标不是为了“形式整齐”，而是为了让文档体系具备以下能力：

1. **可快速定位**：看到路径就大致知道文档用途
2. **可持续扩展**：新文档不会越写越乱
3. **可分层查阅**：一级文档讲方向，二级/三级文档讲细节
4. **可兼容存量**：旧文档不强制一次性大搬家
5. **可作为工程治理工具**：文档路径本身就能反映项目结构与工作方式

---

# 2. 总体原则

## 2.1 docs 允许存在“一级指导文档”

有些文档天然适合作为 `docs/` 根目录下的一级文档保留，不必强行塞进子目录。

典型例子：

- 总体路线图
- 全局设计原则
- 总工程师接管文档
- docs 目录整理规则本身
- 跨多个子系统的指导性文档

这类文档的特点是：

- 作用范围跨模块、跨任务、跨阶段
- 是下层文档的导航或指导依据
- 不适合被某个单独模块目录“收编”

## 2.2 细分文档优先进入子目录

当文档开始明显属于某一类工作时，应优先进入子目录，而不是继续平铺在 `docs/` 根目录。

例如：

- 某个模块状态记录
- 某个具体任务设计稿
- 某类存储方案
- 某个功能契约
- 某个测试矩阵

## 2.3 分类优先于时间

路径应优先表达“它属于什么类别”，而不是单纯按日期堆放。

也就是说，优先这样：

- `docs/tasks/market/detail-contract.md`
- `docs/architecture/storage/data-layering-design.md`

而不是：

- `docs/2026-03-22-market-detail-v2.md`

日期可以写在文档头部、状态记录中，但不应成为主要目录组织方式。

## 2.4 允许渐进迁移，不强制一次性重构全部旧文档

现有文档如果暂时不便移动：

- 可以留在 `docs/` 根目录
- 作为一级文档保留
- 后续在合适时机渐进迁移

规则的目的是建立未来秩序，不是为了制造一次性搬家成本。

---

# 3. 推荐目录层级

建议在 `docs/` 下逐步形成如下结构：

```text
docs/
├── README.md                         # docs 导航页（后续可补）
├── docs-organization-rules.md        # 本规则
├── chief-engineer-handover.md        # 一级指导文档
├── rollout_plan.md                   # 一级路线文档
├── decision-log.md                   # 一级决策文档
├── project-memory.md                 # 一级项目记忆文档
├── code-index.md                     # 一级索引文档
│
├── architecture/                     # 架构类文档
│   ├── frontend/
│   ├── runtime/
│   ├── storage/
│   └── integration/
│
├── tasks/                            # 任务/模块推进文档
│   ├── market/
│   ├── account/
│   ├── engine/
│   ├── mainwindow/
│   ├── compat/
│   └── order-service/
│
├── contracts/                        # 数据契约 / API契约 / 页面契约
│   ├── market/
│   ├── account/
│   ├── orders/
│   └── runtime/
│
├── testing/                          # 测试策略 / 测试矩阵 / 验证说明
│   ├── frontend/
│   ├── runtime/
│   └── integration/
│
├── data/                             # 已存在的数据/存储设计目录
│   ├── *.md
│
└── current-work-status/              # 模块状态续接目录（保留）
    ├── README.md
    ├── market-detail.md
    ├── account.md
    ├── engine.md
    ├── mainwindow.md
    └── compat-retirement.md
```

---

# 4. 各目录职责定义

## 4.1 `docs/` 根目录

用于放置**一级文档**。

### 适合放这里的文档

- 全局路线图
- 决策日志
- 项目长期记忆
- 代码索引
- docs 整理规则
- 总工程师接管文档
- 跨多个模块的高层文档

### 不适合继续堆在这里的文档

- 某个页面 contract 的细节版
- 某个模块单独任务文档
- 某个特定测试计划
- 某项局部重构说明

---

## 4.2 `docs/architecture/`

用于放置偏**系统设计 / 架构方向 / 分层约束**的文档。

### 子目录建议

- `frontend/`
- `runtime/`
- `storage/`
- `integration/`

### 适合内容

- 前端结构收束设计
- runtime service 边界说明
- 存储分层方案
- 事件流/桥接设计

---

## 4.3 `docs/tasks/`

用于放置偏**执行推进**的任务文档。

这是你提议里“docs文件夹-任务文件夹-某某模块/功能任务文档”的核心落点，我认同，而且建议正式采用。

### 推荐规则

- 按模块或功能域建立子文件夹
- 每个任务文档都应能从路径上看出它属于哪一块

### 示例

- `docs/tasks/market/market-detail-hardening.md`
- `docs/tasks/order-service/order-service-boundary-plan.md`
- `docs/tasks/mainwindow/mainwindow-convergence-phase2.md`

### 适合内容

- 某轮具体改造方案
- 某个模块的任务分解
- 某个功能的落地步骤
- 某个阶段的执行计划

---

## 4.4 `docs/contracts/`

用于放置**数据契约 / 页面契约 / 结构契约**。

### 示例

- `docs/contracts/market/market-detail-contract.md`
- `docs/contracts/account/account-view-contract.md`
- `docs/contracts/orders/orders-lifecycle-contract.md`

### 适合内容

- 页面字段 contract
- DTO contract
- 前后层之间的数据语义约定
- authority/source/refresh/status 的正式约束

---

## 4.5 `docs/testing/`

用于放置**测试矩阵、测试策略、验证规则**。

### 示例

- `docs/testing/runtime/runtime-critical-path-test-matrix.md`
- `docs/testing/frontend/frontend-smoke-matrix.md`
- `docs/testing/integration/event-flow-verification.md`

### 适合内容

- 测试范围说明
- 覆盖策略
- 主链路验证矩阵
- 某项重构后的验证方案

---

## 4.6 `docs/data/`

这个目录已经存在，而且当前内容方向清晰，建议保留为**存储 / 数据分层 / 数据模型演进**专用目录。

不建议随意把非数据类文档塞进去。

---

## 4.7 `docs/current-work-status/`

这个目录继续保留，定位非常明确：

> **模块状态续接记录**

它不是总设计目录，不是 contract 目录，也不是 backlog 目录。

它的作用是：

- 记录某模块最近在做什么
- 为什么这么改
- 改了哪些片段
- 风险是什么
- 下一步是什么

这是续接工程上下文的核心目录，应该持续使用。

---

# 5. 命名规则

## 5.1 文件名用 kebab-case

统一建议：

- 全小写
- 单词间用 `-`
- 不要混用空格、中文括号、临时缩写

### 推荐

- `market-detail-contract.md`
- `runtime-critical-path-test-matrix.md`
- `order-service-boundary-plan.md`

### 不推荐

- `MarketDetailContractV2.md`
- `market_detail_new_final2.md`
- `订单生命周期说明最新版.md`

## 5.2 文件名优先表达用途，不表达情绪

文件名应说明：

- 对象是谁
- 文档类型是什么

### 推荐模板

- `<module>-contract.md`
- `<module>-boundary-plan.md`
- `<module>-test-matrix.md`
- `<module>-rollout-plan.md`

## 5.3 日期不写入文件名，除非它本质上是日志类文档

日期应优先写在文档内容头部，而不是文件名里。

例外：

- 明确的日报/记录/归档快照

---

# 6. 一级、二级、三级文档的关系

建议按下面的心智理解：

## 一级文档

放在 `docs/` 根目录。

特点：
- 跨模块
- 指导性强
- 是下层文档的导航与约束

例如：
- `rollout_plan.md`
- `chief-engineer-handover.md`
- `docs-organization-rules.md`

## 二级文档

放在分类子目录下。

特点：
- 属于一个主题域
- 对某类问题给出较完整说明

例如：
- `docs/contracts/market/market-detail-contract.md`
- `docs/testing/runtime/runtime-critical-path-test-matrix.md`

## 三级文档

放在更细的子目录或任务目录中。

特点：
- 强执行导向
- 强局部性
- 面向具体模块/子任务/子问题

例如：
- `docs/tasks/market/market-detail-hardening-phase1.md`
- `docs/tasks/order-service/freeze-pipeline-split-notes.md`

---

# 7. 迁移规则（兼容存量文档）

## 7.1 不搞一次性大搬家

现有文档不要求立刻全部迁移。

## 7.2 新文档优先按新规则落位

从本规则生效后：

- 新文档尽量按分类目录放置
- 只有确实属于一级指导文档的，才放根目录

## 7.3 老文档渐进迁移

当满足以下任一条件时，再考虑迁移旧文档：

- 当前模块正在被重构
- 当前文档正在被重写/大修
- 根目录开始出现明显拥挤
- 某类文档已经形成稳定分类

---

# 8. 当前建议的第一批落地动作

建议先做最小治理，不做大规模搬迁：

1. 在 `docs/` 下新增本规则文档
2. 逐步新增以下目录：
   - `docs/tasks/`
   - `docs/contracts/`
   - `docs/testing/`
   - `docs/architecture/`
3. 新文档按新规则放置
4. 已存在但高度匹配的文档，后续择机迁移

---

# 9. 当前建议的迁移优先级

## 第一优先级：新增目录承接未来文档

先让新文档不再继续堆在根目录。

## 第二优先级：迁移最明确的文档

例如：

- `market-detail-contract.md` → `docs/contracts/market/`
- 未来 `runtime-critical-path-test-matrix.md` → `docs/testing/runtime/`
- 未来具体任务文档 → `docs/tasks/...`

## 第三优先级：保留一级指导文档在根目录

例如：

- `rollout_plan.md`
- `decision-log.md`
- `project-memory.md`
- `chief-engineer-handover.md`
- `docs-organization-rules.md`

---

# 10. 一句话总结

> `docs/` 根目录放一级指导文档；细分任务、契约、测试、架构文档进入子目录；旧文档允许渐进迁移，不强制一次性兼容。

这个规则既能防止继续堆积，又能兼容当前项目现状，适合作为后续文档治理的统一依据。

---

_文档状态：初版规则完成_