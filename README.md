# 跨境电商多智能体经营决策系统（deepagent）

> 基于 **deepagents**（LangChain 多智能体框架）的跨境电商经营决策系统：**经营数据分析师、市场研究员、运营制度专员**三方并行取数，**审计专员独立复核**，最终产出带量化依据的 GO/NO-GO 决策报告。

## ✨ 核心亮点

| 能力 | 说明 |
|---|---|
| **多智能体协同** | 主控 agent 规划 → 3 个领域专家并行取数 → 审计专员复核 → 综合决策 |
| **确定性审计** | 审计专员用 `verify_claims` 重新查库、重新计算，由 [agent-audit](../agent-audit) 逐项比对：报告里的数字与数据库基准值不一致即判不通过——不靠模型自己比较两份结论（[设计说明](docs/audit.md)） |
| **业务化工具** | 库存周转率、滞销预警、毛利分析、退货率统计——把《选品 SOP》的业务公式与红线固化在代码里，不靠 LLM 心算 |
| **多源融合** | MySQL（内部经营数据）+ Tavily（外部市场情报）+ RAGFlow（内部制度知识库） |
| **只读安全** | 数据库工具全部只读 + 参数化 + 表名白名单，防 SQL 注入 |
| **实时进度** | WebSocket 推送 agent 执行过程（调用了哪个子 agent、正在执行哪个工具） |

## 🏗️ 架构

### Agent 拓扑

```
主控 Agent（经营决策团队负责人）
  ├─ 经营数据分析师（MySQL）        ┐
  ├─ 市场研究员（Tavily 联网）       ├─ 三路并行取数
  └─ 运营制度专员（RAGFlow）         ┘
  ↓
审计专员（独立复核）← verify_claims 重算比对 + SOP 红线 + 来源矛盾检查
  ↓
主控 Agent 综合 → 决策报告（Markdown / PDF）
```

### 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | deepagents（LangChain deep agents） |
| LLM | DashScope `qwen-plus`（OpenAI 兼容接口） |
| 结构化数据 | MySQL（跨境电商商品 / 订单 / 库存） |
| 内部知识库 | RAGFlow |
| 外部情报 | Tavily |
| Web 服务 | FastAPI + WebSocket |
| 前端 | Vue 3 + Vite |

## 📁 目录结构

```
deepagent_project/
├── agent/
│   ├── llm.py                  # LLM 初始化
│   ├── load_prompt.py          # 加载 prompts.yaml
│   ├── main_agent.py           # 主 agent 组装 + 执行入口
│   └── sub_agents/             # 4 个子 agent 定义
│       ├── db_sub_agent.py         # 经营数据分析师（MySQL + 业务工具）
│       ├── internet_sub_agent.py   # 市场研究员（Tavily）
│       ├── rag_sub_agent.py        # 运营制度专员（RAGFlow）
│       └── audit_sub_agent.py      # 审计专员（独立复核）
├── api/
│   ├── server.py               # FastAPI 服务 + WebSocket
│   ├── context.py              # ContextVar 会话隔离
│   └── monitor.py              # 实时进度上报
├── tools/
│   ├── mysql_tools.py          # 只读 SQL 工具（防注入）
│   ├── business_tools.py       # 业务化分析工具（固化 SOP 红线）
│   ├── audit_core.py           # 审计判断（纯逻辑，无 I/O，可离线测试）
│   ├── audit_tools.py          # 取基准值 + verify_claims 工具
│   ├── internet_search_tool.py # Tavily 联网检索
│   ├── ragflow_tools.py        # RAGFlow 知识库检索
│   ├── markdown_tools.py       # Markdown 生成
│   ├── pdf_tools.py            # Markdown → PDF
│   └── upload_file_read_tool.py# 上传文件读取
├── utils/                      # 路径解析 / 格式转换 / 日志
├── prompt/prompts.yaml         # 所有 prompt 配置
├── sql/db.sql                  # 跨境电商数据库（建表 + 模拟数据）
├── tests/                      # 审计核心单元测试（不需要数据库）
├── docs/audit.md               # 审计链路设计说明
├── ui/                         # Vue 前端
├── output/                     # 生成的报告目录
├── upload/                     # 用户上传文件目录
├── main.py                     # 后端启动入口
└── pyproject.toml
```

## 🚀 快速开始

### 1. 环境要求

- Python **>= 3.12**
- Node.js（跑前端）
- 一个 MySQL 实例、一个 RAGFlow 实例
- DashScope API Key、Tavily API Key

### 2. 准备外部服务

| 服务 | 用途 |
|---|---|
| MySQL | 存跨境电商经营数据（商品 / 订单 / 库存） |
| RAGFlow | 存内部制度（选品 SOP / 合规清单），并创建聊天助手 |
| DashScope | LLM（qwen-plus） |
| Tavily | 联网市场情报 |

### 3. 安装依赖

```bash
uv sync                          # 推荐（项目自带 uv.lock）
# 或
python -m venv .venv && .venv\Scripts\activate && pip install -e .
```

审计链路依赖同级的 [`agent-audit`](../agent-audit) 仓库（`pyproject.toml` 里已声明，
uv 会按 `[tool.uv.sources]` 的本地路径安装；用 pip 时手动装一次）：

```bash
pip install -e ../agent-audit
```

**前端依赖**：

```bash
cd ui
npm install
```

### 4. 配置 `.env`

```bash
cp .env.example .env
```

按注释填写：RAGFlow 地址/Key、DashScope Key、Tavily Key、MySQL 连接信息。

### 5. 初始化数据库

```bash
mysql -uroot -p --default-character-set=utf8mb4 < sql/db.sql
```

导入后会创建 `crossborder_db`（products / orders / inventory 三表 + 8 个商品模拟数据）。

### 6. 启动后端（端口 8000）

```bash
python main.py
```

### 7. 启动前端（端口 5173）

```bash
cd ui
npm run dev
```

浏览器打开 `http://localhost:5173` 即可提问。

## ⚙️ 配置说明（`.env`）

| 变量 | 说明 |
|---|---|
| `RAGFLOW_API_URL` / `RAGFLOW_API_KEY` | RAGFlow 服务地址 / API Key |
| `DASHSCOPE_BASE_URL` / `DASHSCOPE_API_KEY` | LLM 接口地址 / Key（OpenAI 兼容） |
| `LLM_QWEN_PLUS` | 模型名（默认 `qwen-plus`） |
| `TAVILY_API_KEY` | Tavily 联网搜索 Key |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 连接信息 |

## 🔌 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/task` | 提交任务 `{query, thread_id?}`，后台异步执行 agent |
| POST | `/api/upload` | 上传文件 `files[] + thread_id` |
| GET | `/api/files?path=` | 列出会话输出目录下的文件 |
| GET | `/api/download?path=` | 下载文件（限 output 目录，防越权） |
| WS | `/ws/{thread_id}` | 实时接收 agent 执行进度 |

## 📊 评测（15 条业务问答）

项目内置一套可复现的评测集，覆盖 4 类任务：

| 类别 | 用例数 | 考察点 |
|---|---|---|
| 数据查询 | 4 | 能否正确列出 / 统计数据库中的商品信息 |
| 业务计算 | 5 | 能否用业务工具算对毛利率 / 退货率 / 库存周转 |
| 决策 | 3 | 能否触发审计、给出正确的 GO/NO-GO / 不建议结论 |
| 边界 | 3 | 面对库里没有的数据，能否不编造（幻觉检测） |

**运行方式**：

```bash
python -m evaluation.evaluate                 # 跑全部 15 条
python -m evaluation.evaluate --ids B1,B5,C2  # 只跑指定用例（复跑失败项用）
```

**判分方式**：规则匹配（数字归一化后做关键词校验，可复现）；每跑完一条增量写入 `evaluation/result.json`。

**评测结果**（15 条，规则判分）：

| 指标 | 结果 |
|---|---|
| 准确率 | **86.7%**（13/15） |
| 幻觉率 | **0%**（边界用例未编造库内数据） |
| 决策用例审计触发率 | 1/3（C1/C2 因单条决策链路超过 8 分钟超时，非答错） |
| 总耗时 | 约 31 分钟 |

> 说明：决策类用例涉及「3 个专家 + 审计复核 + 综合」的完整链路，单条耗时可达数分钟；C1/C2 在 8 分钟超时阈值内未完成，属链路延迟问题而非答案错误。

## 🧪 示例问题

- 「评估一下便携榨汁杯值不值得继续做，给出 GO/NO-GO 建议」
- 「哪些商品库存积压最严重？给出滞销清单」
- 「无线蓝牙耳机的毛利率是否达标？最多能降多少钱」
- 「竞品降价 20%，我该不该跟进」

## ❓ FAQ

- **报 `No module named 'tools'`**：用 `python -m tools.xxx` 而不是 `python tools/xxx.py`（前者把项目根目录加入搜索路径）。
- **数据库中文乱码**：导入时加 `--default-character-set=utf8mb4`，且 `db.sql` 开头已有 `SET NAMES utf8mb4`。
- **前端连不上后端**：前端默认连 `localhost:8000`，确保后端先启动。
- **PDF 转换失败**：当前用 Word COM（仅 Windows，需安装 Office），跨平台可换 weasyprint/pandoc。
