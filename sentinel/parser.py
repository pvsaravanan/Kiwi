from dataclasses import dataclass
from typing import Optional
import xml.etree.ElementTree as ET


@dataclass
class FailureRecord:
    test_name: str
    class_name: str
    error_message: str
    stack_trace: str
    failure_type: str
    file_hint: str
    run_id: Optional[str] = None
    timestamp: Optional[str] = None


def parse_junit_xml(path: str) -> list[FailureRecord]:
    root = ET.parse(path).getroot()
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    results = []
    for suite in suites:
        for tc in suite.findall("testcase"):
            node = tc.find("failure") or tc.find("error")
            if node is None:
                continue
            class_name = tc.get("classname", "")
            results.append(FailureRecord(
                test_name=tc.get("name", ""),
                class_name=class_name,
                error_message=node.get("message", ""),
                stack_trace=(node.text or "").strip(),
                failure_type=node.get("type", ""),
                file_hint=class_name.replace(".", "/"),
            ))
    return results
