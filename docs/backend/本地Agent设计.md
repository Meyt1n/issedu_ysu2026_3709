# 本地Agent设计

> 本文档是家健镜系统本地 Agent 的完整设计说明，覆盖 Agent 架构、工具调用、对话管理、记忆系统、权限控制、安全边界。面向后端开发者和算法工程师，作为本地 Agent 实现的权威依据。

## 1. Agent 概述

### 1.1 设计目标

1. **本地运行**：Agent 在家庭服务器本地运行，数据不出网
2. **工具调用**：Agent 可以调用后端 API 执行操作
3. **对话管理**：支持多轮对话和上下文理解
4. **记忆系统**：短期记忆 + 长期记忆，记住用户偏好
5. **安全可控**：所有操作需要用户确认，高风险操作需要授权
6. **可扩展**：支持自定义工具和技能

### 1.2 Agent 能力

| 能力 | 说明 |
| --- | --- |
| 健康问答 | 基于知识库回答健康问题 |
| 药品查询 | 查询药品信息、用法、副作用 |
| 用药提醒 | 设置和管理用药提醒 |
| 体征记录 | 记录和查询生命体征 |
| 风险解读 | 解释健康风险和建议 |
| 家庭管理 | 管理家庭成员和权限 |
| 设备控制 | 控制智能设备（未来扩展） |

### 1.3 技术选型

- **LLM**：本地部署（Ollama / llama.cpp）或 API 调用
- **框架**：LangChain / LlamaIndex / 自研
- **工具调用**：Function Calling / ReAct
- **向量存储**：FAISS / pgvector
- **对话存储**：SQLite / PostgreSQL

## 2. Agent 架构

### 2.1 整体架构

```
用户输入
    ↓
意图识别
    ↓
对话管理器
    ↓
┌─────────────────────────────────────┐
│           Agent 核心循环              │
│  ┌─────────┐    ┌────────────────┐  │
│  │ 思考     │ →  │ 工具选择与调用  │  │
│  └─────────┘    └────────────────┘  │
│       ↑                ↓            │
│  ┌─────────┐    ┌────────────────┐  │
│  │ 观察     │ ←  │ 工具结果处理    │  │
│  └─────────┘    └────────────────┘  │
└─────────────────────────────────────┘
    ↓
回复生成
    ↓
用户输出
```

### 2.2 核心组件

```python
class LocalAgent:
    def __init__(
        self,
        llm: LLMService,
        tools: list[Tool],
        memory: MemorySystem,
        knowledge_base: KnowledgeBase,
        permission_manager: PermissionManager,
    ):
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}
        self.memory = memory
        self.knowledge_base = knowledge_base
        self.permission_manager = permission_manager
        self.max_iterations = 10

    async def run(self, user_input: str, context: AgentContext) -> AgentResponse:
        # 1. 加载记忆
        memories = await self.memory.get_relevant(user_input, context.user_id)

        # 2. 构建初始消息
        messages = self._build_system_prompt(context)
        messages.extend(memories)
        messages.append({"role": "user", "content": user_input})

        # 3. Agent 循环
        for iteration in range(self.max_iterations):
            response = await self.llm.chat_with_tools(
                messages=messages,
                tools=list(self.tools.values()),
            )

            if response.tool_calls:
                # 处理工具调用
                for tool_call in response.tool_calls:
                    result = await self._execute_tool(tool_call, context)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    })
                messages.append(response.message)
            else:
                # 没有工具调用，生成最终回复
                final_response = response.content
                break
        else:
            final_response = "抱歉，我无法在规定步骤内完成这个任务。"

        # 4. 保存记忆
        await self.memory.save_interaction(user_input, final_response, context.user_id)

        return AgentResponse(
            content=final_response,
            tools_used=[tc.name for tc in response.tool_calls] if response.tool_calls else [],
            citations=[],
        )
```

## 3. 工具系统

### 3.1 工具定义

```python
from pydantic import BaseModel, Field
from typing import Callable, Any

class ToolParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None

class Tool:
    name: str
    description: str
    parameters: list[ToolParameter]
    execute: Callable
    requires_confirmation: bool = False
    permission_level: str = "normal"  # normal / sensitive / dangerous

    def to_function_call_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: {"type": p.type, "description": p.description}
                        for p in self.parameters
                    },
                    "required": [p.name for p in self.parameters if p.required],
                },
            },
        }
```

### 3.2 内置工具

#### 查询药品

```python
class QueryMedicineTool(Tool):
    name = "query_medicine"
    description = "查询药品信息，包括用法、用量、副作用、禁忌等"
    parameters = [
        ToolParameter(name="medicine_name", type="string", description="药品名称"),
    ]
    requires_confirmation = False
    permission_level = "normal"

    async def execute(self, medicine_name: str, context: AgentContext) -> str:
        medicine = await medicine_service.get_by_name(medicine_name)
        if not medicine:
            return f"未找到药品：{medicine_name}"

        return (
            f"药品名称：{medicine.name}
"
            f"规格：{medicine.specification}
"
            f"生产厂家：{medicine.manufacturer}
"
            f"用法用量：{medicine.usage}
"
            f"适应症：{medicine.indication}
"
            f"不良反应：{medicine.side_effects}
"
            f"禁忌：{medicine.contraindications}
"
            f"注意事项：{medicine.precautions}"
        )
```

#### 添加药品

```python
class AddMedicineTool(Tool):
    name = "add_medicine"
    description = "为家庭成员添加药品记录"
    parameters = [
        ToolParameter(name="member_id", type="string", description="成员 ID"),
        ToolParameter(name="medicine_name", type="string", description="药品名称"),
        ToolParameter(name="dosage", type="string", description="剂量"),
        ToolParameter(name="frequency", type="string", description="服用频率"),
    ]
    requires_confirmation = True
    permission_level = "sensitive"

    async def execute(
        self,
        member_id: str,
        medicine_name: str,
        dosage: str,
        frequency: str,
        context: AgentContext,
    ) -> str:
        medicine = await medicine_service.create(
            member_id=member_id,
            name=medicine_name,
            dosage=dosage,
            frequency=frequency,
            actor_user_id=context.user_id,
        )
        return f"已添加药品：{medicine.name}，剂量：{medicine.dosage}，频率：{medicine.frequency}"
```

#### 记录体征

```python
class RecordVitalTool(Tool):
    name = "record_vital"
    description = "记录生命体征数据，如血压、血糖、体温等"
    parameters = [
        ToolParameter(name="member_id", type="string", description="成员 ID"),
        ToolParameter(name="vital_type", type="string", description="体征类型",
                     enum=["blood_pressure", "blood_glucose", "temperature", "weight", "heart_rate"]),
        ToolParameter(name="value", type="string", description="体征值"),
        ToolParameter(name="unit", type="string", description="单位"),
    ]
    requires_confirmation = True
    permission_level = "sensitive"

    async def execute(self, member_id: str, vital_type: str, value: str, unit: str, context) -> str:
        vital = await vital_service.record(
            member_id=member_id,
            vital_type=vital_type,
            value=value,
            unit=unit,
            actor_user_id=context.user_id,
        )
        return f"已记录体征：{vital_type} {value} {unit}"
```

#### 查询风险

```python
class QueryRisksTool(Tool):
    name = "query_risks"
    description = "查询家庭成员的当前健康风险"
    parameters = [
        ToolParameter(name="member_id", type="string", description="成员 ID（可选，不填则查询全家）"),
    ]
    requires_confirmation = False
    permission_level = "normal"

    async def execute(self, member_id: str | None = None, context=None) -> str:
        risks = await risk_service.get_active_risks(
            household_id=context.household_id,
            member_id=member_id,
        )
        if not risks:
            return "当前没有活跃的健康风险。"

        lines = []
        for risk in risks:
            lines.append(f"[{risk.risk_level}] {risk.title}：{risk.description}")
        return "\n".join(lines)
```

#### 健康问答

```python
class HealthQATool(Tool):
    name = "health_qa"
    description = "基于知识库回答健康相关问题"
    parameters = [
        ToolParameter(name="question", type="string", description="健康问题"),
    ]
    requires_confirmation = False
    permission_level = "normal"

    async def execute(self, question: str, context) -> str:
        result = await rag_service.search_and_generate(question)
        return result.content
```

### 3.3 工具执行

```python
async def _execute_tool(self, tool_call: ToolCall, context: AgentContext) -> str:
    tool = self.tools.get(tool_call.name)
    if not tool:
        return f"错误：未知工具 {tool_call.name}"

    # 权限检查
    if not await self.permission_manager.check(tool, context):
        return f"错误：无权使用工具 {tool_call.name}"

    # 需要确认的工具
    if tool.requires_confirmation:
        confirmation = await self._request_confirmation(tool, tool_call.arguments, context)
        if not confirmation.approved:
            return "操作已取消。"

    # 执行工具
    try:
        result = await tool.execute(**tool_call.arguments, context=context)
        return result
    except Exception as e:
        logger.error("工具执行失败", tool=tool.name, error=str(e))
        return f"工具执行失败：{str(e)}"
```

## 4. 对话管理

### 4.1 对话状态

```python
class Conversation:
    conversation_id: UUID
    user_id: UUID
    household_id: UUID
    title: str
    messages: list[Message]
    created_at: datetime
    updated_at: datetime

class Message:
    message_id: UUID
    role: str           # user / assistant / tool / system
    content: str
    tool_calls: list | None
    tool_call_id: str | None
    timestamp: datetime
    metadata: dict
```

### 4.2 对话存储

```python
class ConversationStore:
    async def create_conversation(self, user_id: str, household_id: str) -> Conversation:
        conv = Conversation(
            conversation_id=uuid.uuid4(),
            user_id=user_id,
            household_id=household_id,
            title="新对话",
            messages=[],
        )
        db.add(conv)
        await db.commit()
        return conv

    async def add_message(self, conversation_id: str, message: Message):
        conv = await db.get(Conversation, conversation_id)
        conv.messages.append(message)
        conv.updated_at = datetime.now()

        # 自动生成标题（第一条消息）
        if len(conv.messages) == 1:
            conv.title = message.content[:50]

        await db.commit()

    async def get_history(self, conversation_id: str, limit: int = 20) -> list[Message]:
        conv = await db.get(Conversation, conversation_id)
        return conv.messages[-limit:]
```

### 4.3 上下文窗口管理

```python
class ContextManager:
    def __init__(self, max_tokens: int = 4096):
        self.max_tokens = max_tokens

    def build_context(
        self,
        system_prompt: str,
        history: list[Message],
        current_input: str,
    ) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]

        # 从最近的历史开始添加，直到达到 token 限制
        total_tokens = self._count_tokens(system_prompt) + self._count_tokens(current_input)

        for msg in reversed(history):
            msg_tokens = self._count_tokens(msg.content)
            if total_tokens + msg_tokens > self.max_tokens * 0.8:
                break
            messages.insert(1, msg.to_dict())
            total_tokens += msg_tokens

        messages.append({"role": "user", "content": current_input})
        return messages

    def _count_tokens(self, text: str) -> int:
        # 简单估算：中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1.3 token
        return int(len(text) * 1.3)
```

## 5. 记忆系统

### 5.1 记忆类型

| 类型 | 说明 | 存储 | 保留时间 |
| --- | --- | --- | --- |
| 短期记忆 | 当前对话上下文 | 内存/对话存储 | 对话期间 |
| 工作记忆 | 最近 N 轮对话 | 数据库 | 7 天 |
| 长期记忆 | 用户偏好和重要事实 | 向量数据库 | 永久 |
| 情景记忆 | 重要事件和交互 | 数据库 | 永久 |

### 5.2 记忆存储

```python
class MemorySystem:
    def __init__(self, vector_store: VectorStore, db: AsyncSession):
        self.vector_store = vector_store
        self.db = db

    async def save_interaction(self, user_input: str, response: str, user_id: str):
        # 提取关键信息
        key_info = await self._extract_key_info(user_input, response)

        # 向量化并存储
        for info in key_info:
            embedding = await embedding_service.embed(info)
            await self.vector_store.add(
                collection="user_memory",
                id=str(uuid.uuid4()),
                vector=embedding,
                metadata={"user_id": user_id, "content": info, "type": "fact"},
            )

    async def get_relevant(self, query: str, user_id: str, top_k: int = 3) -> list[str]:
        embedding = await embedding_service.embed(query)
        results = await self.vector_store.search(
            collection="user_memory",
            vector=embedding,
            filter={"user_id": user_id},
            top_k=top_k,
        )
        return [r.metadata["content"] for r in results]

    async def _extract_key_info(self, user_input: str, response: str) -> list[str]:
        # 使用 LLM 提取关键信息
        prompt = (
            "从以下对话中提取用户的偏好、习惯、重要事实等关键信息。
"
            "每条信息用一句话概括，不超过 50 字。
"
            "如果没有重要信息，返回空列表。

"
            f"用户：{user_input}
"
            f"助手：{response}

"
            "关键信息："
        )
        result = await llm.chat(prompt)
        return [line.strip("- ") for line in result.split("\n") if line.strip()]
```

### 5.3 记忆使用

```python
# 在系统提示中注入记忆
def build_system_prompt(self, context: AgentContext, memories: list[str]) -> str:
    prompt = '你是家健镜健康助手，帮助家庭管理健康。

已知用户信息：
'
    for memory in memories:
        prompt += f"- {memory}\n"

    prompt += '
规则：
1. 只提供健康信息，不做医疗诊断
2. 重要操作需要用户确认
3. 建议咨询医生或药师
4. 保护用户隐私
'
    return prompt
```

## 6. 权限控制

### 6.1 权限级别

| 级别 | 说明 | 示例工具 |
| --- | --- | --- |
| normal | 普通查询，无需确认 | 查询药品、健康问答 |
| sensitive | 敏感操作，需要确认 | 添加药品、记录体征 |
| dangerous | 危险操作，需要强确认 | 删除数据、修改权限 |

### 6.2 权限检查

```python
class PermissionManager:
    async def check(self, tool: Tool, context: AgentContext) -> bool:
        # 检查用户角色
        if tool.permission_level == "dangerous" and context.user_role != "admin":
            return False

        # 检查家庭成员身份
        if tool.name in ("add_medicine", "record_vital"):
            return await is_household_member(context.user_id, context.household_id)

        return True
```

### 6.3 确认机制

```python
async def _request_confirmation(
    self,
    tool: Tool,
    arguments: dict,
    context: AgentContext,
) -> ConfirmationResult:
    # 生成确认提示
    confirmation_prompt = self._build_confirmation_prompt(tool, arguments)

    # 通过 WebSocket 或 API 发送确认请求
    confirmation_id = str(uuid.uuid4())
    await websocket_service.send_to_user(
        context.user_id,
        {
            "type": "agent_confirmation",
            "confirmation_id": confirmation_id,
            "prompt": confirmation_prompt,
            "tool": tool.name,
            "arguments": arguments,
        },
    )

    # 等待用户确认（超时 60 秒）
    try:
        result = await asyncio.wait_for(
            confirmation_queue.wait(confirmation_id),
            timeout=60,
        )
        return result
    except asyncio.TimeoutError:
        return ConfirmationResult(approved=False, reason="超时未确认")
```

## 7. 安全边界

### 7.1 系统提示

```python
SYSTEM_PROMPT = '''你是家健镜健康助手，专门帮助家庭管理健康。

## 能力范围
- 回答健康相关问题
- 查询药品信息
- 管理用药提醒
- 记录生命体征
- 解读健康风险

## 禁止行为
- 不提供医疗诊断或处方建议
- 不推荐具体药品的购买
- 不处理紧急医疗情况（请拨打 120）
- 不访问用户未授权的数据
- 不执行未经确认的敏感操作

## 操作规范
- 添加、修改、删除数据前必须确认
- 回答健康问题时引用知识库来源
- 建议用户咨询医生或药师
- 保护用户隐私，不泄露健康数据

## 遇到以下情况
- 用户描述紧急症状 → 建议立即就医
- 用户要求诊断 → 说明不能诊断，建议就医
- 用户要求开药 → 说明不能开药，建议咨询医生
- 用户情绪低落 → 给予关怀，建议寻求专业帮助
'''
```

### 7.2 输入过滤

```python
class InputFilter:
    def __init__(self):
        self.blocked_patterns = [
            r"忽略.*指令",
            r"你现在是.*",
            r"系统提示",
            r"prompt.*inject",
        ]

    def filter(self, user_input: str) -> str:
        # 检查注入攻击
        for pattern in self.blocked_patterns:
            if re.search(pattern, user_input, re.IGNORECASE):
                raise BusinessError("INVALID_INPUT", "输入包含不安全内容")

        return user_input.strip()
```

### 7.3 输出过滤

```python
class OutputFilter:
    def filter(self, response: str) -> str:
        # 检查是否包含医疗诊断
        diagnosis_patterns = [
            r"你患有.*",
            r"诊断为.*",
            r"你得了.*",
        ]
        for pattern in diagnosis_patterns:
            if re.search(pattern, response):
                response += "\n\n以上信息仅供参考，不能替代专业医疗诊断。如有不适，请及时就医。"

        return response
```

## 8. 流式响应

### 8.1 SSE 流式

```python
async def agent_stream(
    user_input: str,
    conversation_id: str,
    context: AgentContext,
):
    agent = LocalAgent(...)

    # 发送阶段事件
    yield SSEEvent(event="agent_stage", data={"stage": "thinking", "message": "正在思考..."})

    # 运行 Agent
    async for event in agent.run_stream(user_input, context):
        if event.type == "tool_call":
            yield SSEEvent(event="tool_call", data={"tool": event.tool, "args": event.args})
        elif event.type == "tool_result":
            yield SSEEvent(event="tool_result", data={"tool": event.tool, "result": event.result[:200]})
        elif event.type == "content_delta":
            yield SSEEvent(event="content_delta", data={"delta": event.delta})
        elif event.type == "confirmation_required":
            yield SSEEvent(event="confirmation_required", data=event.confirmation)

    # 完成
    yield SSEEvent(event="done", data={"reply_id": str(uuid.uuid4())})
```

## 9. Agent 检查清单

- [ ] Agent 核心循环正常工作
- [ ] 工具调用准确
- [ ] 工具执行结果正确
- [ ] 权限控制生效
- [ ] 敏感操作需要确认
- [ ] 记忆系统正常存储和检索
- [ ] 对话上下文管理正确
- [ ] 系统提示防止越权
- [ ] 输入输出过滤生效
- [ ] 流式响应正常
- [ ] 错误处理完善
- [ ] 不提供医疗诊断
- [ ] 数据不出本地

---

*本地 Agent 是家庭健康的智能管家。安全、可控、贴心，让健康管理更简单。*
