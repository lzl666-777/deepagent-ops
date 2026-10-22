# 审计专员子 agent：独立复核其他专家助手的数据与结论
from agent.load_prompt import sub_agents_config
from tools.mysql_tools import list_sql_tables, get_table_data, execute_sql_query
from tools.business_tools import (
    calc_inventory_turnover,
    list_slow_moving_products,
    calc_gross_margin,
    calc_return_rate,
)
from tools.audit_tools import verify_claims

audit_sub_agent = {
    "name": sub_agents_config['audit']['name'],
    "description": sub_agents_config['audit']['description'],
    "system_prompt": sub_agents_config['audit']['system_prompt'],
    # verify_claims 是复核的主路径：它重新查库、重新计算，并由 agent-audit 逐项比对，
    # 任何数字偏差直接判不通过 —— 不依赖模型自己比较两份结论。
    # 其余工具只用于补足它覆盖不到的部分（来源矛盾、信息缺失）。
    "tools": [
        verify_claims,
        list_sql_tables,
        get_table_data,
        execute_sql_query,
        calc_inventory_turnover,
        list_slow_moving_products,
        calc_gross_margin,
        calc_return_rate,
    ]
}
