from gg_ingestion.extract.graph_migrate import statements


def test_statements_split_and_comment_stripping():
    text = (
        "// schema constraints\n"
        "CREATE CONSTRAINT a IF NOT EXISTS\nFOR (n:Document) REQUIRE n.doc_key IS UNIQUE;\n"
        "\n"
        "// index\n"
        "CREATE INDEX b IF NOT EXISTS\nFOR (n:Document) ON (n.doc_type);\n"
    )
    parsed = statements(text)
    assert len(parsed) == 2
    assert parsed[0].startswith("CREATE CONSTRAINT a")
    assert parsed[1].startswith("CREATE INDEX b")
    assert all("//" not in s for s in parsed)


def test_statements_empty_input():
    assert statements("// only comments\n") == []
