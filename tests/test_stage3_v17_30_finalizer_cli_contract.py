from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FINALIZER=ROOT/"scripts/finalize_stage3_financial_pdf_values.py"


def argument_specs() -> list[dict[str, object]]:
    tree=ast.parse(FINALIZER.read_text(encoding="utf-8"))
    specs=[]
    for node in ast.walk(tree):
        if not isinstance(node,ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr!="add_argument":
            continue
        flags=[a.value for a in node.args if isinstance(a,ast.Constant) and isinstance(a.value,str) and a.value.startswith("--")]
        if not flags:
            continue
        required=False
        action=None
        type_name=None
        default=None
        for kw in node.keywords:
            if kw.arg=="required" and isinstance(kw.value,ast.Constant):
                required=bool(kw.value.value)
            elif kw.arg=="action" and isinstance(kw.value,ast.Constant):
                action=kw.value.value
            elif kw.arg=="type" and isinstance(kw.value,ast.Name):
                type_name=kw.value.id
            elif kw.arg=="default" and isinstance(kw.value,ast.Constant):
                default=kw.value.value
        specs.append({"flag":flags[0],"required":required,"action":action,"type":type_name,"default":default})
    return specs


def classify(flag: str, type_name: str|None) -> str|None:
    n=flag.lower().replace("_","-")
    if "runtime" in n and "generation" in n:
        return "runtime_generation"
    if "methodology" in n:
        return "methodology"
    if "parser" in n and "method" in n:
        return "parser_method"
    if "gate" in n:
        return "gate"
    if "source" in n and "format" in n:
        return "source_format"
    if "document" in n and ("row" in n or "count" in n):
        if "error" in n:
            return "document_errors"
        return "document_rows"
    if "numeric" in n and ("row" in n or "count" in n or "observation" in n):
        return "numeric_rows"
    if ("unresolved" in n and "tie" in n) or ("tie" in n and "count" in n):
        return "unresolved_ties"
    if "error" in n and "count" in n:
        return "document_errors"
    if n in {"--out","--output"} or "out-root" in n or "output-root" in n or "out-dir" in n or "output-dir" in n:
        return "output"
    if "shard" in n and any(x in n for x in ("root","dir","path","input")):
        return "shard_root"
    if n in {"--input","--root","--artifacts-root","--source-root","--shard-root","--shards-root"}:
        return "shard_root"
    if n in {"--shards","--shard-count","--expected-shards","--expected-shard-count"}:
        return "shard_count" if type_name=="int" or "count" in n or "expected" in n else "shard_root"
    return None


class V1730FinalizerCliContractTest(unittest.TestCase):
    def test_every_required_long_option_is_classifiable(self) -> None:
        specs=argument_specs()
        self.assertTrue(specs)
        unknown=[s["flag"] for s in specs if s["required"] and classify(str(s["flag"]),s["type"] if isinstance(s["type"],str) else None) is None]
        self.assertEqual(unknown,[])

    def test_has_unambiguous_shard_input_and_output_contract(self) -> None:
        specs=argument_specs()
        classes=[classify(str(s["flag"]),s["type"] if isinstance(s["type"],str) else None) for s in specs]
        self.assertIn("shard_root",classes)
        self.assertIn("output",classes)

    def test_no_required_boolean_is_fed_a_string_value(self) -> None:
        specs=argument_specs()
        bad=[s["flag"] for s in specs if s["required"] and s["action"] in {"store_true","store_false"}]
        self.assertEqual(bad,[])


if __name__=="__main__":
    unittest.main()
