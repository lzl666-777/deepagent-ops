# 数据库工具（只读安全）
# 1. list_sql_tables: 列出数据库中所有可用的表，这是了解数据库结构的第一步。
# 2. get_table_data: 读取指定表的前100行数据（校验表名，防SQL注入）。
# 3. execute_sql_query: 执行自定义只读SQL查询（拒绝写操作与多语句）。
import os
import re
from typing import Optional

from dotenv import load_dotenv
from mysql.connector import connect, Error

load_dotenv()

# 生成用于连接数据库的配置
def get_db_config():
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),  # 主机号
        "port": int(os.getenv("MYSQL_PORT", "3306")),  # 端口号
        "user": os.getenv("MYSQL_USER"),  # 用户名
        "password": os.getenv("MYSQL_PASSWORD"),  # 密码
        "database": os.getenv("MYSQL_DATABASE"),  # 数据库名
        "charset": os.getenv("MYSQL_CHARSET", "utf8mb4"),  # 字符集
        "autocommit": True,  # 自动提交事务
    }
    # 过滤掉值为 None 的项
    config = {k: v for k, v in config.items() if v is not None}
    # 检查是否缺少必要配置项
    required_keys = ["user", "password", "database"]
    missing_keys = [k for k in required_keys if k not in config]
    if missing_keys:
        raise ValueError(f"缺少必要配置项: {','.join(missing_keys)}")
    return config


# 配置只在第一次真正连接时解析：
# 原来在模块导入时就执行，导致 `import tools.mysql_tools` 必须有数据库凭据，
# 单元测试连模块都导入不了（审计层因此长期没有测试）。
_db_config: Optional[dict] = None


def _config() -> dict:
    global _db_config
    if _db_config is None:
        _db_config = get_db_config()
    return _db_config


# 只读保护：SQL 中禁止出现的写操作关键词（词边界匹配，避免误判列名如 updated_at）
_FORBIDDEN_SQL_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "grant", "revoke", "replace", "merge", "call",
    "lock", "unlock", "set", "use", "rename",
    # SELECT 也能写文件 / 读服务器文件，只读查询不该包含它们
    "outfile", "dumpfile", "load_file", "into",
)

# 允许的语句开头（只读）
_READ_ONLY_STARTS = ("select", "show", "describe", "explain", "desc", "with")


def _is_read_only_sql(sql: str) -> bool:
    """判断 SQL 是否为只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN），并拒绝多语句。"""
    stripped = sql.strip().rstrip(";").strip().lower()
    if not stripped:
        return False
    # 只允许读语句开头
    if not stripped.startswith(_READ_ONLY_STARTS):
        return False
    # 禁止多语句（防 "; drop table ..." 注入）
    if ";" in sql.rstrip().rstrip(";"):
        return False
    # 词边界匹配写操作关键词
    for kw in _FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{kw}\b", stripped):
            return False
    return True


def _get_valid_tables() -> set:
    """获取数据库中的合法表名集合（用于表名白名单校验）。"""
    try:
        with connect(**_config()) as conn:
            with conn.cursor() as cursor:
                cursor.execute("show tables;")
                return {row[0] for row in cursor.fetchall()}
    except Error:
        return set()


# 1. list_sql_tables: 列出数据库中所有可用的表
def list_sql_tables() -> str:
    """
    列出数据库中所有可用的表
    :return: 有表：可用的表：a,b,c  没表：没有可用的表
    """
    try:
        with connect(**_config()) as conn:
            with conn.cursor() as cursor:
                cursor.execute("show tables;")
                result = cursor.fetchall()
                if not result:
                    return "没有可用的表"
                table_names_str = ','.join([item[0] for item in result])
                return f"可用的表：{table_names_str}"
    except Error as e:
        return f"连接数据库失败：{str(e)}"


# 2. get_table_data: 读取指定表的前100行数据
def get_table_data(table_name: str) -> str:
    """
    获取指定表的前至多100条数据，同时带字段名列表（校验表名合法性，防SQL注入）。
    :param table_name: 表名
    :return: 字段名列表 + 数据行
    """
    # 表名白名单校验：只允许查询数据库中真实存在的表，防止 SQL 注入
    valid_tables = _get_valid_tables()
    if table_name not in valid_tables:
        return f"错误：表 '{table_name}' 不存在或非法，可用的表：{','.join(sorted(valid_tables))}"

    try:
        with connect(**_config()) as conn:
            with conn.cursor() as cursor:
                sql = f"select * from `{table_name}` limit 100;"
                cursor.execute(sql)
                column_names_str = ','.join(cursor.column_names)
                result = cursor.fetchall()
                if not result:
                    return f"查询表{table_name},结果没有数据"
                data_str = '\n'.join([','.join(map(str, item)) for item in result])
                return column_names_str + "\n" + data_str
    except Error as e:
        return f"连接数据库失败：{str(e)}"


# 3. execute_sql_query: 执行自定义只读SQL查询
def execute_sql_query(sql: str) -> str:
    """
    执行只读 SQL 查询（SELECT/SHOW/DESCRIBE/EXPLAIN），拒绝写操作与多语句。
    :param sql: 由大模型生成的只读 SQL
    :return: 字段列表和数据列表的字符串
    """
    if not _is_read_only_sql(sql):
        return "错误：只允许执行只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN），已拒绝写操作或非法语句"

    try:
        with connect(**_config()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                column_names_str = ','.join(cursor.column_names)
                result = cursor.fetchall()
                if not result:
                    return f"执行语句{sql},结果没有数据"
                data_str = '\n'.join([','.join(map(str, item)) for item in result])
                return column_names_str + "\n" + data_str
    except Error as e:
        return f"连接数据库失败：{str(e)}"


if __name__ == '__main__':
    print(list_sql_tables())
    print(get_table_data("products"))
    print(execute_sql_query("select * from products limit 10"))
