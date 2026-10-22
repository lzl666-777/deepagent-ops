# RAG 工具
import os

from dotenv import load_dotenv
from ragflow_sdk import RAGFlow

# 加载.env
load_dotenv()

# 创建ragflow客户端
_ragflow_client = RAGFlow(
    base_url=os.getenv("RAGFLOW_API_URL"),
    api_key=os.getenv("RAGFLOW_API_KEY")
)

# 获取所有助手列表
def get_chat_list() -> str:
    """
    获取ragflow服务中所有的聊天助手信息! 用于后续具体提问的筛选!
    :return:
        返回格式:
        助手名称:xxx , 描述: xx , 关联的知识库: x,x,x,x \n
        助手名称:xxx , 描述: xx , 关联的知识库: x,x,x,x \n
    """
    # 获取所有chat列表
    chats = _ragflow_client.list_chats()
    if not chats:
        return "没有找到任何助手!"
    final_str = ''
    for chat in chats:
        # print(f"chat : {chat}")
        name = chat.name
        description = chat.description
        datasets_str = ",".join([item["name"] for item in chat.datasets])
        final_str += f"助手名称:{name} , 描述: {description} , 关联的知识库: {datasets_str} \n"
        # print(name, description, datasets)
    return final_str

# 找指定助手进行提问
def create_ask_delete(chat_name: str, question: str) -> str:
    """
      向指定的助手提问,并获取返回结果!
      参数 chat_name就是助手的名称,名称需要get_assistant_list查询和确认
          question是本次提问的问题
      返回结果就是提问的回答
    """
    # 根据名称查找对应的chat对象
    chats = _ragflow_client.list_chats(name=chat_name)
    if not chats:
        return "没有找到对应的助手!"
    chat = chats[0]

    # 创建会话
    session = chat.create_session("temp_145")

    # 提问
    result = session.ask(question, stream=True)

    final_str = ""
    # 遍历取出结果
    for chunk in result:
        # print(chunk)
        final_str = chunk.content

    # 删除会话
    chat.delete_sessions([session.id])

    return final_str

if __name__ == "__main__":
    # print(get_chat_list())
    print(create_ask_delete("法律助手", "列出2条刑法规则"))