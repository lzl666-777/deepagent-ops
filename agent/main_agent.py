# [核心] 智能体组装与执行逻辑
import shutil
from pathlib import Path

from deepagents import create_deep_agent

from agent.llm import llm
from agent.load_prompt import main_agent_config
from agent.sub_agents.rag_sub_agent import rag_sub_agent
from agent.sub_agents.db_sub_agent import db_sub_agent
from agent.sub_agents.internet_sub_agent import search_sub_agent
from agent.sub_agents.audit_sub_agent import audit_sub_agent
from api.context import set_thread_context, set_session_context, reset_session_context
from api.monitor import monitor
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content
from tools.decision_gate import gate_final_answer
from utils.logger_utils import logger

main_agent = create_deep_agent(
    model=llm,
    system_prompt=main_agent_config['system_prompt'],
    subagents=[rag_sub_agent, db_sub_agent, search_sub_agent, audit_sub_agent],
    tools=[read_file_content, generate_markdown, convert_md_to_pdf]
)

def _report_agent_process(chunk):
    """Report progress and return the latest final model text (if any)."""
    final_text = ""
    for key, value in chunk.items():
        # print(f"=={key}==")
        # print(value)
        if not value or "messages" not in value:
            continue
        message = value["messages"][-1]
        if key == "model":
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    # 区分子智能体和工具
                    if tool_call["name"] == "task":
                        monitor.report_assistant(tool_call['args']['subagent_type'], tool_call['args']['description'])
                    else:
                        monitor.report_tool(tool_call['name'], tool_call['args'])
            elif message.content:
                # Do not publish a final answer here: it must pass the
                # deterministic decision gate first.
                final_text = str(message.content)
    return final_text

async def run_deep_agent(query: str, thread_id: str):

    # 在调用agent之前，保存thread_id, session_dir_str
    # 保存thread_id
    thread_token = set_thread_context(thread_id)
    # 生成session_dir_str， 再保存session_dir_str，, 并向前端发送session_dir_str
    project_dir = Path(__file__).parents[1].resolve()  # 项目根目录
    session_dir = project_dir / "output" / f"session_{thread_id}"  # 拼接生成sesion目录path对象
    session_dir.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在
    session_dir_str = str(session_dir).replace("\\", "/") # 生成完整路径字符串
    session_token = set_session_context(session_dir_str) # 保存session_dir_str
    monitor.report_session_dir(session_dir_str) # 告诉前端，当前会话的输出目录, 浏览器才能在右侧显示会话文件列表

    # 将upload中的文件拷贝到session目录中
    upload_dir = project_dir / "upload" / f"session_{thread_id}"
    uploaded_info = '' # 关于要优先读取上传的文件的提示词
    if upload_dir.exists():
        # 得到所有文件的列表
        file_names = [ item.name for item in upload_dir.iterdir() if item.is_file()]
        for name in file_names:
            shutil.copy2(upload_dir/name, session_dir/name)
        uploaded_info = (f"\n    [已上传文件] 已加载到工作目录:\n" +
                         "\n".join([f"    - {f}" for f in file_names]) +
                         "\n    请优先使用工具读取并参考这些文件。")

    # 得到工作区目录的相对路径
    relative_session_dir_str = str(session_dir.relative_to(project_dir)).replace("\\", "/")
    path_instruction = f"""
            【工作环境指令】
            工作目录: {relative_session_dir_str}
           
            {uploaded_info}

            规则：
            1. 新生成文件必须保存到工作目录：'{relative_session_dir_str}'
            2. 读取已上传的文件时，请直接将文件名（例如：'开篇.txt'）作为 filename 参数传入（read_file_content）读取工具，不要带上任何目录前缀。
            3. 使用相对路径，禁止使用绝对路径
            4. 若存在上传文件，请先分析内容
            """


    try:
        # 执行agent,遍历过程数据，并将特定数据信息发送给前端
        result = main_agent.astream({
            "messages": [{
                "role": "user",
                "content": f"问题：{query}, 补充描述: {path_instruction}"
            }]
        })
        final_text = ""
        async for chunk in result:
            # 遍历每个chunk,向前端发送当前状态及数据
            latest = _report_agent_process(chunk)
            if latest:
                final_text = latest
        if final_text:
            gated = gate_final_answer(final_text)
            monitor.report_task_result(gated.text)
            if not gated.allowed:
                logger.warning("决策门禁拒绝输出: %s", gated.reason)
                monitor._emit("error", "决策门禁：审计未通过，已阻止决策输出")
    except Exception as e:
        logger.error(f"智能体执行最终失败：{e}")
        monitor._emit("error", f"智能体执行失败：{e}")
    finally:  # 最终都要重置保存的thread_id和session_dir
        reset_session_context(session_token, thread_token)


