"""Parse Android layout XML files to extract UI structure information."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ANDROID_NS = "http://schemas.android.com/apk/res/android"
APP_NS = "http://schemas.android.com/apk/res-auto"


@dataclass
class LayoutInfo:
    filename: str
    referenced_ids: list[str] = field(default_factory=list)
    referenced_strings: list[str] = field(default_factory=list)
    referenced_drawables: list[str] = field(default_factory=list)
    include_layouts: list[str] = field(default_factory=list)
    view_types: list[str] = field(default_factory=list)


_STRING_REF_PATTERN = re.compile(r"@string/(\w+)")
_ID_REF_PATTERN = re.compile(r"@\+?id/(\w+)")
_DRAWABLE_REF_PATTERN = re.compile(r"@(?:drawable|mipmap)/(\w+)")
_LAYOUT_REF_PATTERN = re.compile(r"@layout/(\w+)")


def parse_layout(layout_path: str | Path) -> LayoutInfo:
    """Parse a layout XML file and extract UI structure information."""
    layout_path = Path(layout_path)
    tree = ET.parse(layout_path)
    root = tree.getroot()

    ids: list[str] = []
    strings: list[str] = []
    drawables: list[str] = []
    includes: list[str] = []
    view_types: list[str] = []

    for elem in root.iter():
        # Collect view type (strip namespace prefix if present)
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}")[-1]
        view_types.append(tag)

        # Scan all attributes for references
        for attr_val in elem.attrib.values():
            # IDs
            for match in _ID_REF_PATTERN.finditer(attr_val):
                id_name = match.group(1)
                if id_name not in ids:
                    ids.append(id_name)

            # String references
            for match in _STRING_REF_PATTERN.finditer(attr_val):
                string_name = match.group(1)
                if string_name not in strings:
                    strings.append(string_name)

            # Drawable / mipmap references
            for match in _DRAWABLE_REF_PATTERN.finditer(attr_val):
                drawable_name = match.group(1)
                if drawable_name not in drawables:
                    drawables.append(drawable_name)

        # Include layouts
        if tag == "include":
            layout_attr = elem.get("layout", "")
            match = _LAYOUT_REF_PATTERN.match(layout_attr)
            if match:
                includes.append(match.group(1))

    return LayoutInfo(
        filename=layout_path.name,
        referenced_ids=ids,
        referenced_strings=strings,
        referenced_drawables=drawables,
        include_layouts=includes,
        view_types=view_types,
    )
