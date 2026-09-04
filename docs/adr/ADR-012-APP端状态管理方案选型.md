# ADR-012-APP端状态管理方案选型

> 本文档是家健镜系统 APP 端状态管理方案选型的架构决策记录，覆盖决策背景、候选方案、评估维度、最终决策和实施计划。

## 1. 决策背景

### 1.1 问题陈述

随着 APP 功能不断扩展，页面间状态共享、全局状态管理、异步状态处理的需求日益复杂。需要选择一个统一的状态管理方案，替代当前零散的 setState 和 InheritedWidget 方案。

### 1.2 约束条件

1. 团队熟悉度：团队成员有 React/Vue 经验，对响应式编程有基础
2. 学习成本：不能过于复杂，需要快速上手
3. 性能要求：列表页面需要 60fps
4. 可测试性：需要支持单元测试
5. 社区生态：需要成熟的社区支持

### 1.3 时间线

- 2026-08-01：提出状态管理重构需求
- 2026-08-15：完成候选方案调研
- 2026-08-20：团队评审
- 2026-09-01：最终决策

## 2. 候选方案

### 2.1 Provider

**简介**：Flutter 官方推荐的状态管理方案，基于 InheritedWidget 封装。

**优点**：
- 官方推荐，文档完善
- 学习成本低
- 轻量级，性能好
- 与 Flutter 框架深度集成

**缺点**：
- 复杂状态管理能力有限
- 跨页面状态共享需要多层嵌套
- 异步状态处理不够优雅
- 大型项目维护困难

**适用场景**：中小型应用，简单状态管理。

### 2.2 Bloc (flutter_bloc)

**简介**：基于 BLoC (Business Logic Component) 模式的状态管理库，使用 Stream 处理状态。

**优点**：
- 单向数据流，可预测
- 事件驱动，逻辑清晰
- 强大的异步处理能力
- 优秀的测试支持
- 时间旅行调试
- 社区活跃，生态成熟

**缺点**：
- 学习曲线较陡
- 模板代码较多
- 简单场景显得过重
- 需要理解 Stream 和 Bloc 概念

**适用场景**：中大型应用，复杂业务逻辑，需要严格状态管理。

### 2.3 Riverpod

**简介**：Provider 的改进版，由 Provider 作者开发，解决了 Provider 的一些限制。

**优点**：
- 编译时安全，无运行时异常
- 不依赖 BuildContext
- 支持自动销毁
- 代码简洁
- 测试友好

**缺点**：
- 相对较新，社区生态不如 Bloc
- 概念较多（Provider、Family、AutoDispose）
- 文档相对较少
- 团队熟悉度低

**适用场景**：新项目，追求简洁和类型安全。

### 2.4 GetX

**简介**：一体化解决方案，包含状态管理、路由管理、依赖注入、国际化等。

**优点**：
- 功能全面，一站式解决
- API 简洁，上手快
- 性能优秀
- 内置路由和依赖注入

**缺点**：
- 过于黑盒，调试困难
- 不符合 Flutter 设计哲学
- 社区争议较大
- 大型项目维护困难
- 与标准 Flutter 模式差异大

**适用场景**：快速原型，小型应用，个人项目。

### 2.5 MobX

**简介**：基于响应式编程的状态管理库，源自 JS 生态。

**优点**：
- 响应式编程，自动追踪依赖
- 代码简洁，样板代码少
- 性能优秀，精确更新
- 跨平台经验可复用

**缺点**：
- 需要代码生成（build_runner）
- 魔法行为较多，调试困难
- 学习曲线中等
- 中文文档较少

**适用场景**：有 MobX 经验的团队，追求开发效率。

## 3. 评估维度

### 3.1 评估矩阵

| 维度 | 权重 | Provider | Bloc | Riverpod | GetX | MobX |
| --- | --- | --- | --- | --- | --- | --- |
| 学习成本 | 20% | 9 | 5 | 7 | 9 | 6 |
| 可维护性 | 20% | 6 | 9 | 8 | 5 | 7 |
| 性能 | 15% | 8 | 8 | 8 | 9 | 9 |
| 可测试性 | 15% | 7 | 9 | 9 | 6 | 8 |
| 社区生态 | 10% | 9 | 9 | 7 | 8 | 7 |
| 团队熟悉度 | 10% | 8 | 6 | 4 | 5 | 5 |
| 异步处理 | 10% | 5 | 9 | 8 | 8 | 8 |
| **加权总分** | **100%** | **7.45** | **7.75** | **7.35** | **7.15** | **7.15** |

### 3.2 关键考量

1. **业务复杂度**：家健镜 APP 包含用药提醒、健康数据、在线问诊、商城等多个模块，状态交互复杂，需要强大的状态管理能力。
2. **团队规模**：5 人开发团队，需要统一规范，降低协作成本。
3. **长期维护**：项目预期维护 3 年以上，需要选择稳定、成熟的方案。
4. **测试要求**：医疗健康类应用对质量要求高，需要完善的测试支持。

## 4. 最终决策

### 4.1 决策结果

**选择 Bloc (flutter_bloc) 作为 APP 端主要状态管理方案。**

### 4.2 决策理由

1. **单向数据流**：Bloc 的事件驱动模式让状态变化可预测、可追踪，适合医疗健康类应用的严谨性要求。
2. **强大的异步处理**：用药提醒、数据同步、在线问诊等场景涉及大量异步操作，Bloc 的 Stream 机制天然适合。
3. **优秀的测试支持**：bloc_test 库让 Bloc 测试变得简单，满足医疗应用的质量要求。
4. **社区成熟**：flutter_bloc 是 Flutter 生态中最成熟的状态管理库之一，文档完善，问题可查。
5. **可维护性**：明确的分层（Event → Bloc → State）让大型项目保持结构清晰。

### 4.3 补充方案

- **简单页面状态**：使用 StatefulWidget + setState，避免过度设计。
- **跨页面简单共享**：使用 Provider 作为轻量级补充。
- **表单状态**：使用 flutter_form_bloc 或自管理。

## 5. 实施计划

### 5.1 分阶段迁移

| 阶段 | 时间 | 内容 |
| --- | --- | --- |
| 第一阶段 | 第 1-2 周 | 搭建 Bloc 基础架构，编写规范文档 |
| 第二阶段 | 第 3-4 周 | 迁移核心模块（用户、用药） |
| 第三阶段 | 第 5-6 周 | 迁移健康数据、在线问诊模块 |
| 第四阶段 | 第 7-8 周 | 迁移商城、社区模块 |
| 第五阶段 | 第 9 周 | 清理旧代码，性能优化 |

### 5.2 目录结构

```
lib/
├── blocs/
│   ├── auth/
│   │   ├── auth_bloc.dart
│   │   ├── auth_event.dart
│   │   └── auth_state.dart
│   ├── medicine/
│   │   ├── medicine_bloc.dart
│   │   ├── medicine_event.dart
│   │   └── medicine_state.dart
│   └── health/
│       ├── health_bloc.dart
│       ├── health_event.dart
│       └── health_state.dart
├── repositories/
│   ├── auth_repository.dart
│   ├── medicine_repository.dart
│   └── health_repository.dart
└── pages/
    ├── auth/
    ├── medicine/
    └── health/
```

### 5.3 代码规范

```dart
// Event 命名：过去式动词 + 名词
abstract class MedicineEvent extends Equatable {
  const MedicineEvent();
}

class LoadMedicines extends MedicineEvent {
  const LoadMedicines();
  @override
  List<Object> get props => [];
}

class AddMedicine extends MedicineEvent {
  final Medicine medicine;
  const AddMedicine(this.medicine);
  @override
  List<Object> get props => [medicine];
}

// State 命名：名词 + 状态
abstract class MedicineState extends Equatable {
  const MedicineState();
}

class MedicineInitial extends MedicineState {
  const MedicineInitial();
  @override
  List<Object> get props => [];
}

class MedicineLoading extends MedicineState {
  const MedicineLoading();
  @override
  List<Object> get props => [];
}

class MedicineLoaded extends MedicineState {
  final List<Medicine> medicines;
  const MedicineLoaded(this.medicines);
  @override
  List<Object> get props => [medicines];
}

class MedicineError extends MedicineState {
  final String message;
  const MedicineError(this.message);
  @override
  List<Object> get props => [message];
}
```

## 6. 风险与缓解

### 6.1 风险识别

| 风险 | 概率 | 影响 | 缓解措施 |
| --- | --- | --- | --- |
| 团队学习曲线 | 高 | 中 | 组织培训，编写示例代码，结对编程 |
| 迁移期间 Bug | 中 | 高 | 分阶段迁移，充分测试，保留回滚方案 |
| 性能问题 | 低 | 中 | 性能监控，使用 Equatable，避免不必要重建 |
| 过度设计 | 中 | 低 | 简单页面用 setState，代码审查把关 |

### 6.2 回滚方案

如果 Bloc 方案在实施中遇到严重问题，可回退到 Provider 方案。迁移过程中保持新旧方案共存，逐步替换。

## 7. 决策审查

### 7.1 审查节点

- 迁移完成后 1 个月：评估开发效率
- 迁移完成后 3 个月：评估性能和可维护性
- 每季度：回顾方案适用性

### 7.2 成功指标

1. 新功能开发效率提升 20%
2. 状态相关 Bug 减少 50%
3. 单元测试覆盖率 > 80%
4. 团队满意度 > 4/5

## 8. 参考资料

1. [flutter_bloc 官方文档](https://bloclibrary.dev/)
2. [Bloc 设计模式](https://martinfowler.com/eaaDev/EventSourcing.html)
3. [Flutter 状态管理比较](https://docs.flutter.dev/data-and-backend/state-mgmt/options)
4. [BLoC 模式实战](https://medium.com/flutter-io/building-a-chat-app-with-flutter-and-firebase-1d85f5f5f5f5)

---

*架构决策需要慎重。充分调研、团队评审、分阶段实施，让技术选型服务于业务需求。*
