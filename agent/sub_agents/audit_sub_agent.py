# 审计专员子 agent：独立复核其他专家助手的数据与结论
from agent.load_prompt import sub_agents_config
from tools.mysql_tools import list_sql_tables, get_table_data, execute_sql_query
from tools.business_tools import (
    calc_inventory_turnover,
    list_slow_moving_products,
    calc_gross_margin,
    calc_return_rate,
)

audit_sub_agent = {
    "name": sub_agents_config['audit']['name'],
    "description": sub_agents_config['audit']['description'],
    "system_prompt": sub_agents_config['audit']['system_prompt'],
    # 审计专员掌握数据库只读工具 + 业务指标工具，可独立重新查询、独立复核，
    # 而不是只"转述"其他助手的结论
    "tools": [
        list_sql_tables,
        get_table_data,
        execute_sql_query,
        calc_inventory_turnover,
        list_slow_moving_products,
        calc_gross_margin,
        calc_return_rate,
    ]
}
