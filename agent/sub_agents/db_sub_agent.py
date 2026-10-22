# 数据库助手子agent
from agent.load_prompt import sub_agents_config
from tools.mysql_tools import list_sql_tables, get_table_data, execute_sql_query
from tools.business_tools import (
    calc_inventory_turnover,
    list_slow_moving_products,
    calc_gross_margin,
    calc_return_rate,
)

db_sub_agent = {
    "name": sub_agents_config['db']['name'],
    "description": sub_agents_config['db']['description'],
    "system_prompt": sub_agents_config['db']['system_prompt'],
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
