# DevOps-混沌工程与故障注入

> 本文档是家健镜系统混沌工程与故障注入的完整设计说明，覆盖混沌工程原则、故障注入方法、实验设计、安全防护、结果分析。

## 1. 概述

### 1.1 设计目标

1. 发现系统弱点
2. 验证容错能力
3. 提升恢复速度
4. 建立故障信心
5. 持续改进韧性

### 1.2 混沌工程原则

| 原则 | 说明 |
| --- | --- |
| 建立稳态假设 | 定义系统正常行为 |
| 多样化真实事件 | 模拟真实故障 |
| 在生产环境运行 | 生产最真实 |
| 持续自动化运行 | 常态化执行 |
| 最小化爆炸半径 | 控制影响范围 |

## 2. 故障类型

### 2.1 基础设施故障

```python
class InfrastructureFaults:
    # 服务器故障
    SERVER_DOWN = "server_down"
    SERVER_HIGH_CPU = "server_high_cpu"
    SERVER_MEMORY_LEAK = "server_memory_leak"
    SERVER_DISK_FULL = "server_disk_full"

    # 网络故障
    NETWORK_LATENCY = "network_latency"
    NETWORK_PACKET_LOSS = "network_packet_loss"
    NETWORK_PARTITION = "network_partition"
    NETWORK_BANDWIDTH_LIMIT = "network_bandwidth_limit"

    # 存储故障
    STORAGE_SLOW = "storage_slow"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_DATA_CORRUPTION = "storage_data_corruption"
```

### 2.2 应用故障

```python
class ApplicationFaults:
    # 服务故障
    SERVICE_DOWN = "service_down"
    SERVICE_HIGH_LATENCY = "service_high_latency"
    SERVICE_ERROR = "service_error"

    # 依赖故障
    DEPENDENCY_DOWN = "dependency_down"
    DEPENDENCY_SLOW = "dependency_slow"
    DEPENDENCY_ERROR = "dependency_error"

    # 资源故障
    CONNECTION_POOL_EXHAUSTED = "connection_pool_exhausted"
    THREAD_POOL_EXHAUSTED = "thread_pool_exhausted"
    MEMORY_EXHAUSTED = "memory_exhausted"
```

### 2.3 数据故障

```python
class DataFaults:
    DATABASE_DOWN = "database_down"
    DATABASE_SLOW = "database_slow"
    DATABASE_LOCK = "database_lock"
    CACHE_DOWN = "cache_down"
    CACHE_HIT_LOW = "cache_hit_low"
    MESSAGE_QUEUE_DOWN = "message_queue_down"
    MESSAGE_QUEUE_LATENCY = "message_queue_latency"
```

## 3. 故障注入工具

### 3.1 Chaos Monkey

```python
class ChaosMonkey:
    def __init__(self, kubernetes_client):
        self.k8s = kubernetes_client

    def kill_pod(self, namespace: str, label_selector: str):
        # 随机杀死一个 Pod
        pods = self.k8s.list_namespaced_pod(namespace, label_selector=label_selector)
        if pods.items:
            target = random.choice(pods.items)
            self.k8s.delete_namespaced_pod(target.metadata.name, namespace)
            return f"Killed pod: {target.metadata.name}"
        return "No pods found"

    def kill_random_instance(self, service: str):
        return self.kill_pod("default", f"app={service}")
```

### 3.2 网络故障注入

```python
class NetworkFaultInjector:
    def __init__(self, ssh_client):
        self.ssh = ssh_client

    def add_latency(self, interface: str, latency_ms: int, duration_s: int):
        # 使用 tc 注入延迟
        command = f"tc qdisc add dev {interface} root netem delay {latency_ms}ms"
        self.ssh.execute(command)

        # 定时恢复
        time.sleep(duration_s)
        self.ssh.execute(f"tc qdisc del dev {interface} root")

    def add_packet_loss(self, interface: str, loss_percent: int, duration_s: int):
        command = f"tc qdisc add dev {interface} root netem loss {loss_percent}%"
        self.ssh.execute(command)
        time.sleep(duration_s)
        self.ssh.execute(f"tc qdisc del dev {interface} root")

    def add_bandwidth_limit(self, interface: str, rate: str, duration_s: int):
        command = f"tc qdisc add dev {interface} root tbf rate {rate} burst 32kbit latency 400ms"
        self.ssh.execute(command)
        time.sleep(duration_s)
        self.ssh.execute(f"tc qdisc del dev {interface} root")
```

### 3.3 资源故障注入

```python
class ResourceFaultInjector:
    def __init__(self, ssh_client):
        self.ssh = ssh_client

    def consume_cpu(self, duration_s: int, cores: int = None):
        # 使用 stress-ng 消耗 CPU
        core_flag = f"-c {cores}" if cores else "-c 0"
        command = f"stress-ng {core_flag} -t {duration_s}s"
        self.ssh.execute(command)

    def consume_memory(self, duration_s: int, size_mb: int):
        command = f"stress-ng --vm 1 --vm-bytes {size_mb}M -t {duration_s}s"
        self.ssh.execute(command)

    def consume_disk_io(self, duration_s: int):
        command = f"stress-ng -i 4 -t {duration_s}s"
        self.ssh.execute(command)

    def fill_disk(self, path: str, size_mb: int):
        command = f"dd if=/dev/zero of={path}/tempfile bs=1M count={size_mb}"
        self.ssh.execute(command)
```

## 4. 混沌实验设计

### 4.1 实验模板

```python
class ChaosExperiment:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.steady_state = {}
        self.hypothesis = ""
        self.fault = None
        self.probes = []
        self.stop_conditions = []

    def set_steady_state(self, metrics: dict):
        self.steady_state = metrics

    def set_hypothesis(self, hypothesis: str):
        self.hypothesis = hypothesis

    def inject_fault(self, fault):
        self.fault = fault

    def add_probe(self, probe):
        self.probes.append(probe)

    def add_stop_condition(self, condition):
        self.stop_conditions.append(condition)

    async def run(self):
        # 1. 验证稳态
        print(f"验证稳态: {self.steady_state}")

        # 2. 注入故障
        print(f"注入故障: {self.fault}")
        await self.fault.inject()

        # 3. 运行探针
        for probe in self.probes:
            result = await probe.run()
            print(f"探针结果: {result}")

        # 4. 检查停止条件
        for condition in self.stop_conditions:
            if await condition.check():
                print(f"触发停止条件: {condition}")
                break

        # 5. 恢复故障
        await self.fault.recover()

        # 6. 验证恢复
        print("验证系统恢复")
```

### 4.2 实验示例

```python
class ServiceFailureExperiment(ChaosExperiment):
    def __init__(self):
        super().__init__(
            name="服务故障实验",
            description="验证服务实例故障时系统的容错能力",
        )

        self.set_steady_state({
            "error_rate": "< 1%",
            "p95_latency": "< 500ms",
            "availability": "> 99.9%",
        })

        self.set_hypothesis("当一个服务实例故障时，流量应自动切换到其他实例，系统整体可用性不受影响")

        self.inject_fault(PodKillFault(
            namespace="default",
            label_selector="app=homecare-backend",
        ))

        self.add_probe(HTTPProbe(
            url="https://api.homecare.com/health",
            interval=5,
            duration=120,
        ))

        self.add_stop_condition(ErrorRateExceeds(threshold=0.05))
```

## 5. 安全防护

### 5.1 爆炸半径控制

```python
class BlastRadiusControl:
    def __init__(self):
        self.max_affected_percent = 10  # 最大影响 10%
        self.protected_services = ['database', 'payment']

    def validate_experiment(self, experiment: ChaosExperiment) -> bool:
        # 检查影响范围
        if experiment.fault.affected_percent > self.max_affected_percent:
            return False

        # 检查受保护服务
        if experiment.fault.target_service in self.protected_services:
            return False

        return True

    def limit_traffic(self, percent: int):
        # 只对部分流量注入故障
        pass
```

### 5.2 自动停止

```python
class AutoStop:
    def __init__(self, alert_manager):
        self.alert_manager = alert_manager

    async def check_stop_conditions(self, experiment: ChaosExperiment) -> bool:
        # 检查错误率
        error_rate = await self._get_error_rate()
        if error_rate > 0.05:
            return True

        # 检查延迟
        p95_latency = await self._get_p95_latency()
        if p95_latency > 2.0:
            return True

        # 检查告警
        active_alerts = await self.alert_manager.get_active_alerts()
        if any(a.severity == 'critical' for a in active_alerts):
            return True

        return False
```

### 5.3 紧急回滚

```python
class EmergencyRollback:
    def __init__(self, fault_injector):
        self.injector = fault_injector

    async def rollback_all(self):
        # 恢复所有注入的故障
        await self.injector.recover_all()

        # 通知团队
        await self._notify_team("混沌实验紧急停止，所有故障已恢复")
```

## 6. 结果分析

### 6.1 实验报告

```python
class ExperimentReport:
    def __init__(self, experiment: ChaosExperiment):
        self.experiment = experiment
        self.results = {}

    def add_result(self, probe_name: str, result: dict):
        self.results[probe_name] = result

    def generate_report(self) -> dict:
        return {
            'experiment_name': self.experiment.name,
            'hypothesis': self.experiment.hypothesis,
            'steady_state': self.experiment.steady_state,
            'results': self.results,
            'conclusion': self._draw_conclusion(),
            'recommendations': self._get_recommendations(),
        }

    def _draw_conclusion(self) -> str:
        # 分析结果，得出结论
        pass

    def _get_recommendations(self) -> list[str]:
        # 提出改进建议
        pass
```

### 6.2 韧性评分

```python
class ResilienceScorer:
    def score(self, experiment_results: dict) -> dict:
        scores = {
            'availability': self._score_availability(experiment_results),
            'latency': self._score_latency(experiment_results),
            'recovery_time': self._score_recovery_time(experiment_results),
            'error_handling': self._score_error_handling(experiment_results),
        }

        total = sum(scores.values()) / len(scores)
        scores['total'] = total
        scores['grade'] = self._get_grade(total)

        return scores

    def _get_grade(self, score: float) -> str:
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'
```

## 7. 混沌工程平台

### 7.1 实验调度

```python
class ChaosScheduler:
    def __init__(self):
        self.experiments = []

    def schedule(self, experiment: ChaosExperiment, cron: str):
        self.experiments.append({
            'experiment': experiment,
            'cron': cron,
            'next_run': self._calculate_next_run(cron),
        })

    async def run_due_experiments(self):
        now = datetime.utcnow()
        for item in self.experiments:
            if item['next_run'] <= now:
                await item['experiment'].run()
                item['next_run'] = self._calculate_next_run(item['cron'])
```

### 7.2 实验看板

```python
class ChaosDashboard:
    def get_overview(self) -> dict:
        return {
            'total_experiments': len(self.experiments),
            'success_rate': self._calculate_success_rate(),
            'average_resilience_score': self._calculate_avg_score(),
            'recent_experiments': self._get_recent_experiments(10),
            'weaknesses': self._identify_weaknesses(),
        }
```

## 8. 混沌工程检查清单

- [ ] 基础设施故障
- [ ] 应用故障
- [ ] 数据故障
- [ ] Chaos Monkey
- [ ] 网络故障注入
- [ ] 资源故障注入
- [ ] 实验设计
- [ ] 爆炸半径控制
- [ ] 自动停止
- [ ] 紧急回滚
- [ ] 结果分析
- [ ] 韧性评分

---

*混沌工程是系统韧性的试金石。主动注入故障、发现弱点、持续改进，让系统在真实故障面前从容不迫。*
