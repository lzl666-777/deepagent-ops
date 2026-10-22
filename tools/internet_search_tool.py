# 搜索工具（带自动重试，避免网络抖动导致整条链路失败）
import os
import time

from dotenv import load_dotenv
from langchain_core.tools import tool
from tavily import TavilyClient
from typing import Literal

# 加载.env环境配置，如果在环境变量中配置了，就不会加载.env文件
load_dotenv()

# 创建TavilyClient对象
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# 失败重试次数
MAX_RETRIES = 3


# 定义一个联网搜索工具函数
@tool
def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """使用 Tavily 进行联网搜索（网络抖动时自动重试）"""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return tavily_client.search(
                query=query,
                max_results=max_results,
                include_raw_content=include_raw_content,
                topic=topic,
            )
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * attempt)
    # 重试仍失败：返回错误信息而不是抛异常，让 agent 能继续走后续流程
    return {"error": f"联网搜索失败（已重试 {MAX_RETRIES} 次）: {type(last_err).__name__}: {last_err}"}


if __name__ == "__main__":
    print(type(internet_search))
    internet_search.invoke({"query": "如何使用langchain"})
