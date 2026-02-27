"""Parse Android strings.xml files."""

import xml.etree.ElementTree as ET
from pathlib import Path


def parse_strings(strings_path: str | Path) -> dict[str, str]:
    """Parse strings.xml and return a dict of name → value."""
    tree = ET.parse(strings_path)
    root = tree.getroot()

    result: dict[str, str] = {}
    for string_elem in root.findall("string"):
        name = string_elem.get("name", "")
        if not name:
            continue
        # Get the text content, handling nested elements (like <b>, <i>)
        text = _get_element_text(string_elem)
        result[name] = text

    return result


def filter_strings(
    all_strings: dict[str, str],
    referenced_names: set[str],
) -> dict[str, str]:
    """Return only the strings that are in the referenced set."""
    return {k: v for k, v in all_strings.items() if k in referenced_names}


def _get_element_text(elem: ET.Element) -> str:
    """Extract full text content from an element, including nested markup."""
    # itertext() yields all text in the element tree
    parts = list(elem.itertext())
    return "".join(parts).strip()
