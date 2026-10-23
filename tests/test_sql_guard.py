"""The SQL denylist is a guard, not the only boundary (the session is read-only),
but it should still reject the obvious bypass shapes before they reach MySQL.
"""

import pytest

from tools.mysql_tools import _is_read_only_sql


@pytest.mark.parametrize("sql", [
    "select * from products limit 5",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "show tables",
    "describe products",
    "explain select * from products",
])
def test_read_only_statements_are_allowed(sql):
    assert _is_read_only_sql(sql)


@pytest.mark.parametrize("sql", [
    "delete from products",
    "drop table products",
    "select 1; drop table products",
    "select * from products for update",
    "select * from products into outfile '/tmp/x'",
    "select 1 -- comment",
    "select /*!50000 1 */",
])
def test_write_or_obfuscated_statements_are_rejected(sql):
    assert not _is_read_only_sql(sql)
