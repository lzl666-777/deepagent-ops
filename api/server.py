# [入口] FastAPI 服务端
from contextlib import asynccontextmanager

from utils.logger_utils import logger
import uuid
import asyncio
import uvicorn
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import shutil

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent

# Import agent runner and monitor
# 注意：agent.main_agent 导入时会初始化 main_agent，这可能需要几秒钟
from agent.main_agent import run_deep_agent
from api.monitor import manager
from utils.safe_paths import UnsafeName, ensure_within, safe_filename, safe_thread_id

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     loop = asyncio.get_running_loop()
#     manager.set_loop(loop)
#     print(f"--[Server] WebSocket Manager bound to loop: {id(loop)}")
#
#     yield
#
# app = FastAPI(title="DeepAgents API", lifespan=lifespan)
app = FastAPI(title="DeepAgents API")

# 挂载输出目录，以便前端访问生成的静态文件
# 假设输出目录位于项目根目录下的 output
output_dir = project_root / "output"
output_dir.mkdir(exist_ok=True)

# 定义上传目录 updated
upload_dir = project_root / "upload"
upload_dir.mkdir(exist_ok=True)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """
    服务启动时，获取当前运行的事件循环，并绑定到 WebSocket 管理器。
    确保后台线程能通过 run_coroutine_threadsafe 准确投递消息。
    """
    loop = asyncio.get_running_loop()
    manager.set_loop(loop)
    logger.info(f"[Server] WebSocket Manager bound to loop: {id(loop)}")


class TaskRequest(BaseModel):
    query: str
    thread_id: str = None

@app.post("/api/task")
async def run_task(request: TaskRequest):
    """
    智能体任务启动接口 (Run Agent Task)。

    目标：
    1. 接收用户的自然语言指令。
    2. 在后台异步启动 Agent 执行逻辑。
    3. 返回会话 ID，供前端通过 WebSocket 订阅实时进度。

    执行步骤：
    1. 获取或生成 thread_id。
    2. 触发异步任务 (asyncio.create_task)。
    3. 立即返回响应，不阻塞 HTTP 线程。

    Args:
        request (TaskRequest): 包含用户 query 和可选 thread_id 的请求体。
    """
    # 1. [ID 初始化] thread_id 会拼进 output/session_<id>，必须先校验，不能直接拼
    try:
        thread_id = safe_thread_id(request.thread_id or str(uuid.uuid4()))
    except UnsafeName as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 2. [后台执行] 异步运行 Agent，不阻塞主线程
    # 注意：这里简单的使用 asyncio.create_task 触发，由 main_agent 内部负责实时推送
    asyncio.create_task(run_deep_agent(request.query, thread_id)) # 再将携程对象添加到当前事件循环中执行
    # asyncio.run(run_deep_agent(request.query, thread_id)) #创建一个新的事件循环，再将携程对象添加到事件循环中执行

    # 3. [立即响应]
    return {"status": "started", "thread_id": thread_id}


@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...), thread_id: str = Form(...)):
    """
    文件上传接口 (File Upload)。

    目标：
    1. 接收用户上传的一个或多个文件。
    2. 保存到 `upload/session_{thread_id}` 目录。
    3. 供 Agent 在后续任务中读取和分析。

    Args:
        files (List[UploadFile]): 文件对象列表。
        thread_id (str): 关联的任务会话 ID。
    """
    # 1. [校验] 先把所有名字验一遍再落盘：一个非法文件名不该留下半批垃圾。
    #    file.filename 和 thread_id 都来自客户端，而它们都会参与路径拼接 + open()。
    try:
        safe_id = safe_thread_id(thread_id)
        names = [safe_filename(file.filename) for file in files]
    except UnsafeName as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # 2. [目录准备] 确保上传目录存在
    target_dir = upload_dir / f"session_{safe_id}"
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    # 3. [保存] 遍历并写入文件
    for file, name in zip(files, names):
        # ensure_within 是纵深防御：清洗已经去掉了目录成分，这里再确认一次没越界
        file_path = ensure_within(target_dir, target_dir / name)
        # 使用二进制模式写入，支持各种文件格式 (图片、PDF、文本等)
        # shutil.copyfileobj 高效复制文件流，避免一次性加载大文件到内存
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_files.append(name)

    # 4. [响应] 返回成功保存的文件列表
    return {"status": "uploaded", "files": saved_files}

@app.get("/api/download")
async def download_file(path: str):
    """
    文件下载接口 (File Download)。

    目标：
    1. 根据绝对路径下载文件。
    2. 严格的安全检查，防止越权访问。

    Args:
        path (str): 文件的绝对路径 (通常从 list_files 接口获取)。
    """
    # 1. [安全检查] 路径解析与越权校验
    try:
        abs_path = Path(path).resolve()
        output_abs = output_dir.resolve()

        # 必须确保请求的文件在 output 目录下
        if not abs_path.is_relative_to(output_abs):
            return {"error": "拒绝访问: 只能下载输出目录下的文件"}
    except Exception:
        return {"error": "无效的路径参数"}

    # 2. [存在性检查]
    if not abs_path.exists():
        return {"error": "文件不存在"}

    # 3. [响应] 返回文件流 (浏览器自动触发下载)
    return FileResponse(abs_path, filename=abs_path.name)


@app.get("/api/files")
async def list_files(path: str):
    """
    文件列表查询接口 (File Explorer)。

    目标：
    1. 列出指定目录下的所有生成文件。
    2. 提供文件元数据（大小、时间、下载链接）。
    3. 严格的安全检查，防止路径遍历攻击。

    Args:
        path (str): 目标目录的绝对路径 (必须在 output 目录下)。
    """
    # 1. [调试] 打印请求路径
    logger.debug(f"请求文件列表: {path}")

    try:
        # 2. [解析] 获取绝对路径对象
        abs_path = Path(path).resolve()
        output_abs = output_dir.resolve()

        # 3. [安全] 检查路径是否越界 (Path Traversal Check)
        if not abs_path.is_relative_to(output_abs):
            logger.warning(f"拒绝访问: {abs_path} 不在 {output_abs} 目录下")
            return {"error": "拒绝访问: 只能访问输出目录下的文件"}

    except Exception as e:
        logger.error(f"路径解析失败: {e}")
        return {"error": f"路径无效: {e}"}

    # 4. [检查] 目录是否存在
    if not abs_path.exists():
        return {"error": "目录不存在"}

    files = []
    try:
        # 5. [遍历] 递归查找所有文件
        for file_path in abs_path.rglob("*"):
            if file_path.is_file():
                # 计算相对路径，生成下载 URL
                stat = file_path.stat()
                files.append({
                    "name": file_path.name,
                    "type": "file",
                    "path": str(file_path),
                    # "url": f"/outputs/{url_path}",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime
                })

    except Exception as e:
        logger.error(f"遍历文件失败: {e}")
        return {"error": str(e)}

    # 6. [排序] 按修改时间倒序排列 (最新的在前)
    files.sort(key=lambda x: x.get("mtime", 0), reverse=True)
    logger.debug(f"找到 {len(files)} 个文件")
    return {"files": files}

# 当浏览器请求 ws://localhost:8000/ws/thread_123 时：
# 1. 路由匹配 ：FastAPI 发现这个 URL 匹配了你写的 @app.websocket("/ws/{thread_id}") 。
# 2. 创建对象 ：FastAPI (基于 Starlette) 会立刻在 主事件循环 中实例化一个 WebSocket 对象。
#    - 这个对象封装了底层的 TCP 连接、HTTP 握手信息、以及后续的消息收发方法 ( send_text , receive_text 等)。
# 3. 注入参数 ：FastAPI 自动把这个刚创建好的 WebSocket 对象，作为参数传给你的 websocket_endpoint(websocket, ...) 函数。
@app.websocket("/ws/{thread_id}")
async def websocket_endpoint(websocket: WebSocket, thread_id: str):
    """
    WebSocket 实时通讯核心接口 (Real-time Communication)。

    目标：
    1. 建立长连接，实现服务端与前端的双向通信。
    2. 绑定 `thread_id`，实现会话级消息隔离。
    3. 维持心跳 (Keep-Alive)，防止连接超时。

    执行步骤：
    1. 握手：接受 WebSocket 连接请求。
    2. 注册：将连接实例绑定到 `monitor.manager`，关联 `thread_id`。
    3. 循环：进入消息监听循环，处理前端发送的心跳或指令。
    4. 异常：捕获断开连接异常，清理资源。

    Args:
        websocket (WebSocket): WebSocket 连接实例。
        thread_id (str): 当前会话的唯一标识。
    """
    # 1. [注册] 建立连接并绑定到管理器
    await manager.connect(websocket, thread_id)

    try:
        # 2. [循环] 保持连接活跃
        while True:
            # 3. [监听] 接收前端消息 (通常是 ping 心跳)
            data = await websocket.receive_text()

            # 4. [响应] 回复 pong 消息
            await websocket.send_json({
                "type": "pong",
                "message": f"服务端已收到: {data}"
            })

    except WebSocketDisconnect:
        # 5. [清理] 客户端主动断开
        manager.disconnect(websocket, thread_id)
        logger.info(f"客户端已断开: {thread_id}")

    except Exception as e:
        # 6. [异常] 发生错误时断开
        logger.error(f"WebSocket 连接异常: {e}")
        manager.disconnect(websocket, thread_id)


def start_server():
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False)