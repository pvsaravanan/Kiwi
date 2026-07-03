import xml.etree.ElementTree as ET
from dataclasses import dataclass


class AdapterError(RuntimeError):
    pass


@dataclass
class FailureRecord:
    test_name: str
    class_name: str
    error_message: str
    stack_trace: str
    failure_type: str
    file_hint: str
    run_id: str | None = None
    timestamp: str | None = None


def parse_junit_xml(path: str) -> list[FailureRecord]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise AdapterError(f"Cannot parse JUnit XML at {path}: {exc}") from exc

    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    records = []
    for suite in suites:
        for case in suite.findall("testcase"):
            node = case.find("failure")
            if node is None:
                node = case.find("error")
            if node is None:
                continue
            class_name = case.get("classname", "")
            records.append(FailureRecord(
                test_name=case.get("name", ""),
                class_name=class_name,
                error_message=node.get("message", ""),
                stack_trace=(node.text or "").strip(),
                failure_type=node.get("type", ""),
                file_hint=class_name.replace(".", "/"),
            ))
    return records
