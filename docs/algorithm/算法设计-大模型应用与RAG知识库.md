# 算法设计-大模型应用与RAG知识库

> 本文档是家健镜系统大模型应用与 RAG 知识库的完整设计说明，覆盖大模型集成、知识库构建、检索增强、提示工程、模型评估。

## 1. 概述

### 1.1 设计目标

1. 回答准确率 > 85%
2. 响应延迟 < 3 秒
3. 支持医疗领域问答
4. 知识可更新
5. 回答可溯源

### 1.2 应用场景

| 场景 | 说明 | 模型 |
| --- | --- | --- |
| 健康咨询 | 常见健康问题问答 | RAG + LLM |
| 用药指导 | 用药咨询和提醒 | RAG + LLM |
| 报告解读 | 健康报告智能解读 | LLM |
| 智能客服 | 自动回复用户问题 | RAG + LLM |
| 内容生成 | 健康科普文章生成 | LLM |

## 2. 大模型集成

### 2.1 模型接口

```python
from openai import AsyncOpenAI

class LLMService:
    def __init__(self, api_key: str, base_url: str, model: str = "gpt-4"):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> str:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def stream_chat(
        self,
        messages: list[dict],
        on_token: callable,
    ):
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                on_token(chunk.choices[0].delta.content)
```

### 2.2 多模型支持

```python
class ModelFactory:
    @staticmethod
    def create_model(model_type: str, config: dict) -> LLMService:
        if model_type == "openai":
            return LLMService(
                api_key=config["api_key"],
                base_url="https://api.openai.com/v1",
                model=config.get("model", "gpt-4"),
            )
        elif model_type == "azure":
            return LLMService(
                api_key=config["api_key"],
                base_url=config["endpoint"],
                model=config["deployment_name"],
            )
        elif model_type == "local":
            return LocalLLMService(
                model_path=config["model_path"],
            )
        else:
            raise ValueError(f"Unsupported model type: {model_type}")
```

### 2.3 本地模型部署

```python
class LocalLLMService:
    def __init__(self, model_path: str):
        from transformers import AutoTokenizer, AutoModelForCausalLM
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            device_map="auto",
        )

    async def chat(self, messages: list[dict], **kwargs) -> str:
        prompt = self._format_messages(messages)
        inputs = self.tokenizer(prompt, return_tensors="pt").to("cuda")
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=kwargs.get("max_tokens", 1000),
            temperature=kwargs.get("temperature", 0.7),
        )
        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)
```

## 3. 知识库构建

### 3.1 文档加载

```python
from langchain.document_loaders import (
    PyPDFLoader,
    TextLoader,
    WebBaseLoader,
    DirectoryLoader,
)

class DocumentLoader:
    def __init__(self):
        self.loaders = {
            '.pdf': PyPDFLoader,
            '.txt': TextLoader,
            '.md': TextLoader,
        }

    def load_file(self, file_path: str) -> list[Document]:
        ext = os.path.splitext(file_path)[1].lower()
        loader_class = self.loaders.get(ext)
        if not loader_class:
            raise ValueError(f"Unsupported file type: {ext}")
        loader = loader_class(file_path)
        return loader.load()

    def load_directory(self, dir_path: str) -> list[Document]:
        loader = DirectoryLoader(dir_path, glob="**/*")
        return loader.load()
```

### 3.2 文本分块

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

class TextChunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )

    def split(self, documents: list[Document]) -> list[Document]:
        return self.splitter.split_documents(documents)
```

### 3.3 向量化

```python
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import Chroma

class VectorStore:
    def __init__(self, persist_directory: str = "./data/vectorstore"):
        self.embeddings = HuggingFaceEmbeddings(
            model_name="shibing624/text2vec-base-chinese",
            model_kwargs={"device": "cuda"},
        )
        self.vectorstore = Chroma(
            persist_directory=persist_directory,
            embedding_function=self.embeddings,
        )

    def add_documents(self, documents: list[Document]):
        self.vectorstore.add_documents(documents)
        self.vectorstore.persist()

    def similarity_search(self, query: str, k: int = 5) -> list[Document]:
        return self.vectorstore.similarity_search(query, k=k)

    def similarity_search_with_score(self, query: str, k: int = 5):
        return self.vectorstore.similarity_search_with_score(query, k=k)
```

## 4. RAG 检索增强

### 4.1 RAG 流程

```
用户问题
    ↓
查询改写（Query Rewriting）
    ↓
向量检索（Vector Search）
    ↓
重排序（Reranking）
    ↓
上下文构建（Context Building）
    ↓
大模型生成（LLM Generation）
    ↓
答案 + 引用来源
```

### 4.2 RAG 服务

```python
class RAGService:
    def __init__(self, vectorstore: VectorStore, llm: LLMService):
        self.vectorstore = vectorstore
        self.llm = llm

    async def answer(self, question: str, k: int = 5) -> dict:
        # 1. 检索相关文档
        docs = self.vectorstore.similarity_search(question, k=k)

        # 2. 构建上下文
        context = self._build_context(docs)

        # 3. 构建提示词
        prompt = self._build_prompt(question, context)

        # 4. 调用大模型
        answer = await self.llm.chat([
            {"role": "system", "content": "你是一个专业的健康医疗助手。"},
            {"role": "user", "content": prompt},
        ])

        return {
            "answer": answer,
            "sources": [
                {"title": doc.metadata.get("title"), "source": doc.metadata.get("source")}
                for doc in docs
            ],
            "context": context,
        }

    def _build_context(self, docs: list[Document]) -> str:
        context_parts = []
        for i, doc in enumerate(docs, 1):
            context_parts.append(f"[文档{i}]\n{doc.page_content}")
        return "\n\n".join(context_parts)

    def _build_prompt(self, question: str, context: str) -> str:
        return (
            '请根据以下参考资料回答用户问题。如果参考资料中没有相关信息，请回答"根据现有资料无法回答"。\n\n'
            '参考资料：\n'
            + context + '\n\n'
            '用户问题：' + question + '\n\n'
            '请给出详细、准确的回答，并在回答中标注引用的文档编号。'
        )
```

### 4.3 查询改写

```python
class QueryRewriter:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def rewrite(self, query: str) -> list[str]:
        prompt = (
            '请将以下用户问题改写为3个不同的搜索查询，用于知识库检索。\n'
            '要求：\n'
            '1. 保持原意\n'
            '2. 使用不同的表达方式\n'
            '3. 包含同义词\n\n'
            '原问题：' + query + '\n\n'
            '请输出3个查询，每行一个。'
        )

        response = await self.llm.chat([{"role": "user", "content": prompt}])
        queries = [q.strip() for q in response.split("\n") if q.strip()]
        return queries[:3]
```

### 4.4 重排序

```python
class Reranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, docs: list[Document], top_k: int = 3) -> list[Document]:
        pairs = [(query, doc.page_content) for doc in docs]
        scores = self.model.predict(pairs)

        scored_docs = list(zip(docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        return [doc for doc, _ in scored_docs[:top_k]]
```

## 5. 提示工程

### 5.1 系统提示词

```python
SYSTEM_PROMPT = (
    "你是家健镜健康助手，一个专业的医疗健康咨询AI。\n\n"
    "你的职责：\n"
    "1. 回答用户关于健康、用药、疾病的问题\n"
    "2. 基于提供的参考资料给出准确回答\n"
    "3. 对于不确定的问题，建议咨询专业医生\n"
    "4. 不提供诊断和处方建议\n\n"
    "回答规范：\n"
    "- 使用中文回答\n"
    "- 结构清晰，分点说明\n"
    "- 引用参考资料时标注来源\n"
    "- 涉及紧急情况时建议立即就医\n\n"
    "免责声明：本助手提供的信息仅供参考，不能替代专业医疗建议。"
)
```

### 5.2 少样本提示

```python
FEW_SHOT_PROMPT = (
    "示例1：\n"
    "用户：高血压患者应该注意什么？\n"
    "助手：高血压患者需要注意以下几点：\n"
    "1. 饮食：减少钠盐摄入，每日不超过5克\n"
    "2. 运动：每周至少150分钟中等强度有氧运动\n"
    "3. 用药：按时服药，不要自行停药\n"
    "4. 监测：定期测量血压并记录\n\n"
    "示例2：\n"
    "用户：阿莫西林怎么吃？\n"
    "助手：阿莫西林的一般用法：\n"
    "- 成人：每次0.5g，每6-8小时一次\n"
    "- 儿童：按体重计算，每日20-40mg/kg\n"
    "- 饭后服用，减少胃肠道刺激\n"
    "- 疗程一般5-7天，需遵医嘱\n\n"
    "注意：青霉素过敏者禁用，用药前需确认过敏史。\n\n"
    "现在请回答：\n"
    "用户：{question}\n"
    "助手："
)
```

### 5.3 思维链

```python
COT_PROMPT = (
    "请一步步思考并回答以下问题。\n\n"
    "问题：{question}\n\n"
    "请按以下格式回答：\n"
    "思考过程：\n"
    "1. 分析问题\n"
    "2. 查找相关知识\n"
    "3. 组织答案\n\n"
    "最终答案：\n"
    "[详细回答]"
)
```

## 6. 模型评估

### 6.1 评估指标

```python
class RAGEvaluator:
    def __init__(self):
        self.metrics = {
            'faithfulness': 0,
            'relevance': 0,
            'completeness': 0,
            'accuracy': 0,
        }

    def evaluate_faithfulness(self, answer: str, context: str) -> float:
        # 检查回答是否基于上下文
        pass

    def evaluate_relevance(self, answer: str, question: str) -> float:
        # 检查回答是否相关
        pass

    def evaluate(self, question: str, answer: str, context: str) -> dict:
        return {
            'faithfulness': self.evaluate_faithfulness(answer, context),
            'relevance': self.evaluate_relevance(answer, question),
            'overall': sum(self.metrics.values()) / len(self.metrics),
        }
```

### 6.2 测试集

```python
class TestSet:
    def __init__(self):
        self.questions = [
            {
                'question': '高血压的诊断标准是什么？',
                'expected_answer': '收缩压≥140mmHg和/或舒张压≥90mmHg',
                'category': '疾病知识',
            },
            {
                'question': '阿莫西林的常见副作用有哪些？',
                'expected_answer': '恶心、腹泻、皮疹等',
                'category': '用药指导',
            },
        ]

    def run_evaluation(self, rag_service: RAGService) -> dict:
        results = []
        for item in self.questions:
            result = rag_service.answer(item['question'])
            results.append({
                'question': item['question'],
                'answer': result['answer'],
                'expected': item['expected_answer'],
                'category': item['category'],
            })
        return {'total': len(results), 'results': results}
```

## 7. 知识库管理

### 7.1 知识更新

```python
class KnowledgeManager:
    def __init__(self, vectorstore: VectorStore):
        self.vectorstore = vectorstore

    def add_document(self, file_path: str, metadata: dict):
        loader = DocumentLoader()
        docs = loader.load_file(file_path)
        chunker = TextChunker()
        chunks = chunker.split(docs)
        for chunk in chunks:
            chunk.metadata.update(metadata)
        self.vectorstore.add_documents(chunks)

    def remove_document(self, source: str):
        self.vectorstore.vectorstore.delete(
            where={"source": source}
        )

    def list_documents(self) -> list[dict]:
        pass
```

## 8. 大模型检查清单

- [ ] 模型接口
- [ ] 多模型支持
- [ ] 本地部署
- [ ] 文档加载
- [ ] 文本分块
- [ ] 向量化
- [ ] RAG 服务
- [ ] 查询改写
- [ ] 重排序
- [ ] 提示工程
- [ ] 模型评估
- [ ] 知识库管理

---

*大模型与 RAG 结合，让健康咨询更智能。精准检索、增强生成、可溯源回答，让 AI 助手专业可靠。*
