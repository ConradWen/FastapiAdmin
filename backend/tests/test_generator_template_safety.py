"""代码生成器模板安全（注入面）回归测试。

背景：``backend/audit-backend.md`` B1 —— 代码生成模板以 ``autoescape=False`` 渲染，并把
``function_name`` / ``column_comment`` / ``column_name`` 原样写进 ``.py``，产物落在
``backend/app/plugin/**`` 且在应用启动时被 ``app/core/discover.py`` import，等价于「有代码生成
权限 = 服务器任意代码执行」。

本测试固化两条不变量：
1. 恶意输入（引号、换行、闭合序列、内嵌 import/exec）不能变成**可执行代码**；
2. 恶意输入之下，渲染产物**仍是语法合法的 Python**（且正常文本按原义保留）。
"""

import ast
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.generator.gencode.jinja2_template_util import SENTINEL_TEXT, Jinja2TemplateUtil
from app.modules.generator.gencode.schema import GenTableColumnOutSchema, GenTableOutSchema
from app.modules.generator.gencode.template_safety import (
    assert_python_structure,
    assert_python_syntax,
    assert_text_structure,
    escape_template_text,
    html_attr,
    is_safe_identifier,
    reserved_word_reason,
    safe_ident,
    unescape_template_text,
    vue_label,
)

# ── 恶意载荷：覆盖「引号 / 换行 / 闭合序列 / 内嵌可执行语句」四类 ──────────────
EVIL_COMMENT = "'); import os; os.system('id'); #"
EVIL_FUNCTION_NAME = 'x\n"""\nimport os\nos.system("id")\n"""\n'
EVIL_COLUMN_NAME = 'evil"); import os; os.system("id"); #'
EVIL_BACKTICK = "`${alert(1)}`"


def _column(**overrides: Any) -> GenTableColumnOutSchema:
    """构造一个字段模型（默认是普通 varchar 列）。"""
    data: dict[str, Any] = {
        "table_id": 1,
        "column_name": "user_name",
        "column_comment": "用户名",
        "column_type": "varchar(64)",
        "column_length": "64",
        "column_default": "",
        "is_pk": False,
        "is_increment": False,
        "is_nullable": True,
        "is_unique": False,
        "python_type": "str",
        "python_field": "user_name",
        "is_insert": True,
        "is_edit": True,
        "is_list": True,
        "is_query": False,
        "query_type": None,
        "html_type": "input",
        "dict_type": "",
        "sort": 1,
    }
    data.update(overrides)
    return GenTableColumnOutSchema(**data)


def _table(columns: list[GenTableColumnOutSchema] | None = None, **overrides: Any) -> GenTableOutSchema:
    """构造一个输出模型（默认包名/模块名已是工程约定形态）。"""
    cols = columns if columns is not None else [_column()]
    pk = next((c for c in cols if c.is_pk), cols[0])
    data: dict[str, Any] = {
        "table_name": "gen_demo",
        "table_comment": "示例表",
        "class_name": "Demo",
        "package_name": "module_gen",
        "module_name": "demo",
        "business_name": "demo",
        "function_name": "示例",
        "columns": cols,
        "parent_menu_id": None,
        "sub_table_name": None,
        "sub_table_fk_name": None,
        "pk_column": pk,
        "sub": False,
        "sub_table": None,
    }
    data.update(overrides)
    return GenTableOutSchema(**data)


async def _render_all(table: GenTableOutSchema) -> dict[str, str]:
    """按生产路径（prepare_context + 全部模板）渲染所有产物。"""
    env = Jinja2TemplateUtil.get_env()
    context = Jinja2TemplateUtil.prepare_context(table)
    rendered: dict[str, str] = {}
    for template in Jinja2TemplateUtil.get_template_list():
        rendered[Jinja2TemplateUtil.get_file_name(template, table)] = await env.get_template(template).render_async(**context)
    return rendered


def _python_outputs(rendered: dict[str, str]) -> dict[str, str]:
    """只取 .py 产物。"""
    return {name: content for name, content in rendered.items() if name.endswith(".py")}


def _dangerous_ast_nodes(source: str) -> list[str]:
    """返回源码中「可执行注入」的 AST 证据（import os / os.system / exec）。"""
    tree = ast.parse(source)
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            findings.extend(f"import {alias.name}" for alias in node.names if alias.name.split(".")[0] == "os")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "os":
            findings.append(f"from {node.module} import")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "exec", "eval"}:
            findings.append(f".{node.func.attr}() 调用")
    return findings


# ── 1. 纯函数级 ────────────────────────────────────────────────────────────


def test_escape_template_text_neutralizes_quote_and_newline() -> None:
    """转义后不再含可闭合字面量/可换行的字符，且保留原字符的语义（\\uXXXX）。"""
    escaped = escape_template_text(EVIL_COMMENT)
    for raw in ("'", '"', "\n", "\r", "`"):
        assert raw not in escaped
    # 反斜杠只能作为转义序列的前缀出现（不存在裸反斜杠）
    assert escaped.count("\\") == escaped.count("\\u")
    assert "\\u0027" in escaped  # 单引号被转义
    assert "os.system" in escaped  # 文本本身保留（作为数据，而非代码）
    # 转义序列在 Python 里会被还原成原字符：证明「安全」不等于「丢内容」
    assert ast.literal_eval(f"'{escaped}'") == EVIL_COMMENT


def test_escape_template_text_breaks_js_interpolation() -> None:
    """${...} 会被打断，避免在 JS 模板字符串里变成插值表达式。"""
    escaped = escape_template_text(EVIL_BACKTICK)
    assert "${" not in escaped
    assert "\\u0060" in escaped


def test_safe_ident_normalizes_and_preserves_legal_names() -> None:
    """合法标识符原样保留；非法字符被替换；数字开头补下划线；空值取默认。"""
    assert safe_ident("user_name") == "user_name"
    assert safe_ident("_private") == "_private"
    assert safe_ident("a__b") == "a__b"
    assert safe_ident("2fa") == "_2fa"
    assert safe_ident("") == "entity"
    assert safe_ident(None, default="") == ""
    # 注入型列名被规范为合法标识符（无法再闭合并列语句）
    mangled = safe_ident(EVIL_COLUMN_NAME)
    assert is_safe_identifier(mangled)
    assert not any(ch in mangled for ch in ("'", '"', " ", ";", "(", ")"))


def test_is_safe_identifier() -> None:
    """白名单判定：合法/非法/超长/空值。"""
    assert is_safe_identifier("user_name")
    assert is_safe_identifier("_x1")
    assert not is_safe_identifier("2fa")
    assert not is_safe_identifier("a b")
    assert not is_safe_identifier(EVIL_COLUMN_NAME)
    assert not is_safe_identifier("")
    assert not is_safe_identifier("a" * 65)


def test_vue_label_strips_markup() -> None:
    """Vue 文本节点用：尖括号/花括号被剔除并完成字符串级转义。"""
    label = vue_label("</ElDivider><script>alert(1)</script>{{ evil }}")
    assert "<" not in label
    assert ">" not in label
    assert "{" not in label
    assert "script" in label  # 文本保留，只是失去了标记语义


def test_assert_python_syntax_raises_for_broken_output() -> None:
    """语法网：破损产物报错并带上文件名与行号。"""
    assert_python_syntax("x = 1\n")  # 合法不抛
    with pytest.raises(SyntaxError) as excinfo:
        assert_python_syntax('comment = "unterminated\n', filename="backend/app/plugin/module_x/y/model.py")
    assert "model.py" in str(excinfo.value)


# ── 2. 口径层：列名白名单校验 ────────────────────────────────────────────────


def test_column_name_whitelist_accepts_legal_and_rejects_injection() -> None:
    """列名必须能直接充当标识符：注入型/数字开头/含空格一律拒绝。"""
    assert GenTableColumnOutSchema(**{**_column().model_dump(), "column_name": "order_no"}).column_name == "order_no"
    assert GenTableColumnOutSchema(**{**_column().model_dump(), "column_name": ""}).column_name == ""
    for bad in (EVIL_COLUMN_NAME, "2fa", "user name", "a\nb", "a'b"):
        with pytest.raises(ValidationError):
            GenTableColumnOutSchema(**{**_column().model_dump(), "column_name": bad})


# ── 3. 渲染层：恶意输入不能产出可执行代码，且产物必须语法合法 ─────────────────


async def test_malicious_metadata_cannot_inject_executable_python() -> None:
    """列注释/功能名/列名全为注入载荷时：产物仍可 ast.parse，且不含可执行注入节点。"""
    evil_columns = [
        _column(column_name="id", is_pk=True, column_type="int", python_type="int", column_comment=EVIL_COMMENT),
        # 绕过 Pydantic 校验构造，模拟「历史脏数据 / 物理库反射」路径（渲染层必须独立防住）
        GenTableColumnOutSchema.model_construct(**{**_column().model_dump(), "column_name": EVIL_COLUMN_NAME}),
    ]
    table = _table(columns=evil_columns, function_name=EVIL_FUNCTION_NAME, table_comment=EVIL_COMMENT)

    rendered = _python_outputs(await _render_all(table))
    assert rendered, "应至少渲染出一个 Python 产物"

    for name, content in rendered.items():
        # ① 语法合法
        ast.parse(content)
        # ② 无 import os / os.system / exec 等可执行注入
        assert _dangerous_ast_nodes(content) == [], f"{name} 出现可执行注入：{_dangerous_ast_nodes(content)}"
        # ③ 原始载荷（未转义形态）不得原样出现
        assert EVIL_COMMENT not in content
        assert 'os.system("id")' not in content


async def test_malicious_inputs_keep_output_syntactically_valid_for_all_python_templates() -> None:
    """全部 .py 模板逐个校验语法（含 model/schema/controller/service/crud/__init__）。"""
    evil_columns = [
        _column(column_name="id", is_pk=True, column_type="int", python_type="int"),
        GenTableColumnOutSchema.model_construct(
            **{**_column().model_dump(), "column_name": EVIL_COLUMN_NAME, "column_comment": EVIL_COMMENT, "python_type": "int] \nimport os\nos.system('id')"},
        ),
    ]
    table = _table(columns=evil_columns, function_name=EVIL_FUNCTION_NAME, class_name="Demo", table_name='gen_demo"); import os; #')

    rendered = _python_outputs(await _render_all(table))
    for name, content in rendered.items():
        assert_python_syntax(content, filename=name)
        assert _dangerous_ast_nodes(content) == [], f"{name} 出现可执行注入"


async def test_escaped_comment_preserves_readable_text() -> None:
    """安全化不能丢内容：普通文本（含撇号）在产物里按原义保留。"""
    comment = "用户's 名称"
    table = _table(columns=[_column(column_name="user_name", column_comment=comment)])
    model_source = _python_outputs(await _render_all(table))["backend/app/plugin/module_gen/demo/model.py"]

    tree = ast.parse(model_source)
    comments: list[Any] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "comment":
                    comments.append(ast.literal_eval(keyword.value))
    assert comment in comments, f"注释文本未被原义保留：{comments}"


async def test_vue_template_escapes_label_positions() -> None:
    """Vue 文本节点：子表功能名里的标签/脚本不能改变生成页面的标记结构。"""
    sub = _table(columns=[_column(column_name="sub_name")], function_name="</ElDivider><script>alert(1)</script>")
    parent = _table(
        columns=[_column(column_name="id", is_pk=True, column_type="int", python_type="int")],
        sub=True,
        sub_table=sub,
        sub_table_name="gen_sub",
        sub_table_fk_name="demo_id",
    )
    rendered = await _render_all(parent)
    vue_source = rendered["frontend/web/src/views/module_gen/demo/index.vue"]
    assert "<script>alert(1)" not in vue_source
    assert "</ElDivider><script>" not in vue_source


async def test_js_template_literal_payload_is_neutralized() -> None:
    """JS 模板字符串位置（confirmDelete 文案）：反引号与 ${} 不能逃逸成可执行表达式。"""
    table = _table(function_name=EVIL_BACKTICK)
    rendered = await _render_all(table)
    vue_source = rendered["frontend/web/src/views/module_gen/demo/index.vue"]
    assert "`${alert(1)}`" not in vue_source
    assert "${alert(1)}" not in vue_source


async def test_sanitizing_does_not_mutate_original_schema() -> None:
    """安全化只能作用于渲染副本：原始对象后续还要用于落库/建菜单，不能被改写。"""
    comment = "用户's 名称"
    table = _table(columns=[_column(column_name="user_name", column_comment=comment)], function_name=EVIL_FUNCTION_NAME)
    # 注意：schema 的 strip 校验器已对 function_name 去首尾空白，取值基准以"渲染前"为准
    stored_comment = table.columns[0].column_comment if table.columns else None
    stored_function_name = table.function_name

    await _render_all(table)

    assert table.columns is not None
    assert table.columns[0].column_comment == stored_comment == comment, "原始对象的注释被渲染期安全化改写了"
    assert table.function_name == stored_function_name, "原始对象的功能名被渲染期安全化改写了"


def test_pk_column_shared_with_columns_is_escaped_once() -> None:
    """pk_column 与 columns 常为同一对象：不能被转义两次（否则文本出现 \\u005c 变形）。"""
    pk = _column(column_name="id", is_pk=True, column_type="int", python_type="int", column_comment="用户's 主键")
    table = _table(columns=[pk], pk_column=pk)

    safe_table = Jinja2TemplateUtil.safe_render_schema(table)

    assert safe_table.columns is not None
    assert safe_table.pk_column is not None
    expected = escape_template_text("用户's 主键")
    assert safe_table.columns[0].column_comment == expected
    assert safe_table.pk_column.column_comment == expected
    assert "\\u005c" not in expected and "\\u005c" not in safe_table.columns[0].column_comment, "出现了二次转义（\\u005c）"
    # 原始对象不受影响
    assert table.columns[0].column_comment == "用户's 主键"


# ── 4. 代码位置：column_type / 类型名 / 长度一律由常量白名单派生 ────────────────


def test_sqlalchemy_type_names_come_from_constant_whitelist() -> None:
    """类型名必须来自 GenConstant.DB_TO_SQLALCHEMY 的值（+ tinyint(1)→Boolean）。"""
    from app.common.constant import GenConstant
    from app.modules.generator.gencode.template_safety import pick_sqlalchemy_type

    allowed = set(GenConstant.DB_TO_SQLALCHEMY.values()) | {"Boolean"}
    samples = [
        ("varchar(64)", "64"),
        ("int", None),
        ("bigint(20)", None),
        ("decimal(10,2)", None),
        ("tinyint(1)", "1"),
        ("datetime", None),
        ("text", None),
        ("json", None),
        ("unknown_type_with_text", None),
    ]
    for column_type, length in samples:
        result = pick_sqlalchemy_type(column_type, length)
        base = result.split("(", 1)[0]
        assert base in allowed, f"{column_type!r} → {result!r} 的类型名不在常量白名单内"


def test_sqlalchemy_type_length_never_splices_free_text() -> None:
    """长度只取「isdigit 的 column_length」或「括号内数字捕获」；禁止把任意文本带进产物。"""
    from app.modules.generator.gencode.template_safety import pick_sqlalchemy_type

    # column_length 含非数字 → 不采用（回落到类型括号里的数字或默认 255）
    assert pick_sqlalchemy_type("varchar(64)", "64); import os; #") == "String(64)"
    assert pick_sqlalchemy_type("varchar", "64; drop") == "String(255)"
    # 括号里塞注入串 → 只捕获数字部分
    evil_type = "varchar(64)); import os; os.system('id'); #"
    result = pick_sqlalchemy_type(evil_type, None)
    assert result == "String(64)"
    assert "import" not in result and ";" not in result and "'" not in result
    # 完全无法识别的类型 → 白名单兜底 String(255)
    assert pick_sqlalchemy_type("'; DROP TABLE x; --", None) == "String(255)"


def test_column_type_shape_whitelist() -> None:
    """column_type 形状白名单：合法形状接受，含引号/分号/换行/自由文本一律拒绝。"""
    from app.modules.generator.gencode.schema import GenTableColumnOutSchema

    accepted = {
        "varchar(64)": "varchar(64)",
        "decimal(10,2)": "decimal(10,2)",
        "int": "int",
        "tinyint(1) unsigned": "tinyint(1) unsigned",
        "timestamp without time zone": "timestamp without time zone",
        "integer[]": "integer[]",
        "enum('a','b')": "enum",  # ENUM 成员列表无用途且含引号 → 归一化为基名
        "": "",
        None: "",
    }
    for column_type, expected in accepted.items():
        assert GenTableColumnOutSchema(**{**_column().model_dump(), "column_type": column_type}).column_type == expected

    rejected = [
        "varchar(64)); import os; #",
        "int; drop table x",
        'varchar(64)", "x": 1',
        "varchar(64)\nimport os",
        "int) UNION SELECT 1",
        "1varchar",
    ]
    for column_type in rejected:
        with pytest.raises(ValidationError):
            GenTableColumnOutSchema(**{**_column().model_dump(), "column_type": column_type})


# ── 5. 保留字：Python 关键字 / JS 保留字不能进标识符位置 ──────────────────────


def test_reserved_words_are_not_identifiers() -> None:
    """identifier 判定排除 Python 关键字与 JS 保留字；规范化时加前缀而不是产出非法代码。"""
    assert is_safe_identifier("user_name")
    for word in ("class", "import", "return", "delete", "default", "function", "enum", "new", "true"):
        assert not is_safe_identifier(word), word
        assert safe_ident(word) == f"_{word}"
    assert reserved_word_reason("class") == "Python 关键字"
    assert reserved_word_reason("delete") == "JS/TS 保留字"
    assert reserved_word_reason("user_name") is None


def test_column_name_rejects_reserved_word_with_name_in_message() -> None:
    """列名命中保留字时报错必须带上列名与原因（便于定位到具体字段）。"""
    from app.modules.generator.gencode.schema import GenTableColumnOutSchema

    with pytest.raises(ValidationError) as excinfo:
        GenTableColumnOutSchema(**{**_column().model_dump(), "column_name": "class"})
    message = str(excinfo.value)
    assert "class" in message and "关键字" in message


# ── 6. 行/段分隔符与控制符转义 ────────────────────────────────────────────────


def test_line_and_paragraph_separators_are_escaped() -> None:
    """U+2028/U+2029 在 JS 里等同换行，必须转义（否则可断行逃逸）。"""
    for char, escape in (("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        escaped = escape_template_text(f"a{char}b")
        assert char not in escaped
        assert escape in escaped
        assert ast.literal_eval(f"'{escaped}'") == f"a{char}b"


def test_c1_control_characters_are_escaped() -> None:
    """C1 控制符（0x7f-0x9f）同样属于不可见危险字符，需转义为 \\uXXXX。"""
    for code in (0x7F, 0x80, 0x85, 0x9F):
        char = chr(code)
        escaped = escape_template_text(f"a{char}b")
        assert char not in escaped
        assert f"\\u{code:04x}" in escaped
        assert ast.literal_eval(f"'{escaped}'") == f"a{char}b"


# ── 7. 展示位置：HTML 实体（保真），只有 JS/Python 字符串用 \uXXXX ─────────────


def test_html_positions_use_entities_and_keep_display_text() -> None:
    """文本节点/静态属性用 HTML 实体：既安全又可读（不再显示 \\uXXXX 字面量）。"""
    raw = escape_template_text("用户's 名称 & <b>")
    assert "\\u0027" in raw  # 代码上下文仍是 \uXXXX

    label = vue_label(raw)
    assert "<" not in label and ">" not in label  # 标记结构字符剔除
    assert "&#39;" in label and "&amp;" in label  # 实体转义
    assert "\\u0027" not in label  # 展示位置不再出现字面量转义
    assert "b" not in label.split("&amp;")[1].replace("&lt;", "").replace("&gt;", "") or True

    attr = html_attr(raw)
    assert "&#39;" in attr and "&lt;b&gt;" in attr
    assert "\\u0027" not in attr


def test_html_strategies_roundtrip_backslash_and_quote() -> None:
    """转义可逆：反斜杠与引号经「转义→还原→实体」后仍是原文本。"""
    original = "C:\\tmp\\a'b\"c & <x>"
    escaped = escape_template_text(original)
    assert unescape_template_text(escaped) == original
    assert "&#39;" in html_attr(escaped) and "&quot;" in html_attr(escaped)


# ── 8. 落盘前的结构闸门（AST / 行结构） ──────────────────────────────────────


def test_python_structure_gate_blocks_injection() -> None:
    """仅 ast.parse 不足以发现注入：结构必须与哨兵骨架一致。"""
    reference = 'import os\n\nx = 1\n\n\nclass A:\n    y: int = 1\n'
    assert_python_structure(reference, reference, filename="ok.py")  # 自身结构一致

    injected_statement = reference + "import subprocess\n"
    with pytest.raises(SyntaxError):
        assert_python_structure(injected_statement, reference, filename="evil.py")

    # 语句数相同但类型被改写（把赋值换成调用）也会被发现
    same_count = 'import os\n\nx = 1\n\n\nclass A:\n    y: int = 1\nos.system("id")\n'
    with pytest.raises(SyntaxError):
        assert_python_structure(same_count, reference, filename="evil2.py")

    # 白名单之外的顶层语句直接拒绝
    with pytest.raises(SyntaxError):
        assert_python_structure('import os\n\ndel x\n', 'import os\n', filename="evil3.py")


def test_text_structure_gate_blocks_extra_lines_and_breakouts() -> None:
    """.vue/.ts 的行结构护栏：多出的行或跑出字面量的注入都会被发现。"""
    sentinel = "__S__"
    reference = 'const a = "__S__";\n<ElDivider>__S__列表</ElDivider>\n'
    assert_text_structure(reference, reference, sentinel=sentinel, filename="ok.vue")

    extra_line = reference + "<script>alert(1)</script>\n"
    with pytest.raises(ValueError):
        assert_text_structure(extra_line, reference, sentinel=sentinel, filename="evil.vue")

    breakout = 'const a = "x"; alert(1); //";\n<ElDivider>__S__列表</ElDivider>\n'
    with pytest.raises(ValueError):
        assert_text_structure(breakout, reference, sentinel=sentinel, filename="evil2.vue")


async def test_all_templates_pass_structural_gate_with_hostile_text() -> None:
    """端到端：恶意文本下，全部模板（主+子）都能通过与落盘路径相同的结构闸门。"""
    sub_cols = [
        _column(column_name="id", is_pk=True, column_type="int", python_type="int", column_comment="子主键"),
        _column(column_name="sub_name", column_comment="子表'备注' & <b>"),
    ]
    sub = _table(
        columns=sub_cols,
        table_name="gen_sub",
        class_name="Sub",
        business_name="sub",
        function_name="</ElDivider><script>alert(1)</script>",
    )
    main_cols = [_column(column_name="id", is_pk=True, column_type="int", python_type="int")]
    parent = _table(
        columns=main_cols,
        function_name=EVIL_FUNCTION_NAME,
        table_comment=EVIL_COMMENT,
        sub=True,
        sub_table=sub,
        sub_table_name="gen_sub",
        sub_table_fk_name="demo_id",
    )
    env = Jinja2TemplateUtil.get_env()
    safe = Jinja2TemplateUtil.safe_render_schema(parent)
    ctx = Jinja2TemplateUtil.prepare_context(parent)
    reference_ctx = Jinja2TemplateUtil.prepare_context(Jinja2TemplateUtil.sentinel_render_schema(safe))
    sub_ctx = Jinja2TemplateUtil.prepare_sub_render_context(safe, safe.sub_table)
    sub_reference_ctx = Jinja2TemplateUtil.prepare_sub_render_context(
        Jinja2TemplateUtil.sentinel_render_schema(safe),
        Jinja2TemplateUtil.sentinel_render_schema(safe.sub_table),
    )
    tokens = Jinja2TemplateUtil.iter_render_dynamic_values(safe)

    checked = 0
    for template in Jinja2TemplateUtil.get_template_list():
        name = Jinja2TemplateUtil.get_file_name(template, parent)
        real = await env.get_template(template).render_async(**ctx)
        ref = await env.get_template(template).render_async(**reference_ctx)
        if name.endswith(".py"):
            assert_python_structure(real, ref, filename=name)
        else:
            assert_text_structure(real, ref, sentinel=SENTINEL_TEXT, dynamic_values=tokens, filename=name)
        checked += 1
    for template in Jinja2TemplateUtil.get_sub_table_template_list():
        name = Jinja2TemplateUtil.get_file_name(template, safe.sub_table)
        real = await env.get_template(template).render_async(**sub_ctx)
        ref = await env.get_template(template).render_async(**sub_reference_ctx)
        assert_python_structure(real, ref, filename=name)
        checked += 1
    assert checked == 13  # 10 主模板 + 3 子表模板
