from wap.cli.ch_init import split_statements


def test_split_statements_drops_comments_and_blanks() -> None:
    sql = """
    -- a comment; with a semicolon
    CREATE DATABASE IF NOT EXISTS wap;

    CREATE TABLE t (x UInt8) ENGINE = Memory;
    """
    assert split_statements(sql) == [
        "CREATE DATABASE IF NOT EXISTS wap",
        "CREATE TABLE t (x UInt8) ENGINE = Memory",
    ]
