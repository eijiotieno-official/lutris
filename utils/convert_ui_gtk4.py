#!/usr/bin/env python3
"""Convert a GTK3 .ui file to GTK4 builder XML format."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET

REMOVE_PROPERTIES = {
    "visible",
    "can-focus",
    "can_focus",
    "no-show-all",
    "receives-default",
    "can-default",
    "has-default",
    "relief",
    "use-stock",
    "always-show-image",
    "show-close-button",
    "window-position",
    "type-hint",
    "type_hint",
    "skip-taskbar-hint",
    "skip_pager_hint",
    "show-menubar",
    "draw-indicator",
    "shadow-type",
    "primary-icon-activatable",
    "primary-icon-sensitive",
}

CLASS_REPLACEMENTS = {
    "GtkAlignment": "GtkBox",
    "GtkHBox": "GtkBox",
    "GtkVBox": "GtkBox",
    "GtkButtonBox": "GtkBox",
}

PACKING_TO_CHILD_TYPE = {
    "end": "end",
    "start": "start",
    "center": None,
    "bottom": "end",
    "top": "start",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _convert_packing_to_layout(packing: ET.Element) -> dict[str, str]:
    layout: dict[str, str] = {}
    for prop in packing:
        if _local_name(prop.tag) != "property":
            continue
        name = prop.attrib.get("name", "")
        value = prop.text or ""
        if name == "left-attach":
            layout["column"] = value
        elif name == "top-attach":
            layout["row"] = value
        elif name == "position" and "column" not in layout:
            layout["column"] = value
    return layout


def _should_remove_property(name: str) -> bool:
    return name in REMOVE_PROPERTIES


def _process_element(element: ET.Element) -> None:
    tag = _local_name(element.tag)

    if tag == "object":
        class_name = element.attrib.get("class")
        if class_name in CLASS_REPLACEMENTS:
            element.attrib["class"] = CLASS_REPLACEMENTS[class_name]

    if tag == "requires" and element.attrib.get("lib", "").startswith("gtk"):
        element.attrib["lib"] = "gtk"
        element.attrib["version"] = "4.0"

    children = list(element)
    packing: ET.Element | None = None
    layout_props: dict[str, str] = {}
    child_type: str | None = None
    overlay_index: str | None = None
    overlay_pass_through: str | None = None

    for child in children:
        child_tag = _local_name(child.tag)
        if child_tag == "packing":
            packing = child
            for prop in child:
                if _local_name(prop.tag) != "property":
                    continue
                name = prop.attrib.get("name", "")
                value = prop.text or ""
                if name == "pack-type":
                    child_type = PACKING_TO_CHILD_TYPE.get(value)
                elif name == "index":
                    overlay_index = value
                elif name == "pass-through":
                    overlay_pass_through = value
                else:
                    layout_props.update(_convert_packing_to_layout(child))
        elif child_tag == "property":
            prop_name = child.attrib.get("name", "")
            if _should_remove_property(prop_name):
                element.remove(child)
            elif prop_name == "border-width":
                child.attrib["name"] = "margin-top"
                for suffix, value in (
                    ("margin-bottom", child.text),
                    ("margin-start", child.text),
                    ("margin-end", child.text),
                ):
                    extra = ET.Element("property", name=suffix)
                    extra.text = value
                    element.append(extra)

    if packing is not None:
        parent_tag = _local_name(element.tag)
        if parent_tag == "child":
            if child_type:
                element.attrib["type"] = child_type
            if overlay_index is not None:
                element.attrib["type"] = "overlay"
            if overlay_pass_through is not None:
                element.attrib["pass-through"] = overlay_pass_through
            if layout_props and _local_name(element[0].tag if list(element) else "") == "object":
                obj = element.find("object") or element.find("{*}object")
                if obj is not None and _local_name(obj.tag) == "object":
                    obj_class = obj.attrib.get("class", "")
                    if obj_class == "GtkGrid" or any(
                        _local_name(sib.tag) == "layout" for sib in list(element) if sib is not packing
                    ):
                        layout = ET.Element("layout")
                        for key, value in layout_props.items():
                            prop = ET.SubElement(layout, "property", name=key)
                            prop.text = value
                        element.insert(list(element).index(packing), layout)
        element.remove(packing)

    # Unwrap GtkViewport: move its child to the ScrolledWindow
    if tag == "object" and element.attrib.get("class") == "GtkViewport":
        parent = element  # caller must handle - we mark for replacement
        element.attrib["_unwrap_viewport"] = "1"

    for child in list(element):
        _process_element(child)

    if tag == "child":
        obj = None
        for sub in element:
            if _local_name(sub.tag) == "object":
                obj = sub
                break
        if obj is not None and obj.attrib.pop("_unwrap_viewport", None):
            # handled at parent level below
            pass


def _unwrap_viewports(root: ET.Element) -> None:
    for parent in root.iter():
        for child in list(parent):
            if _local_name(child.tag) != "child":
                continue
            obj = next((c for c in child if _local_name(c.tag) == "object"), None)
            if obj is None or obj.attrib.get("class") != "GtkViewport":
                continue
            viewport_child = next((c for c in obj if _local_name(c.tag) == "child"), None)
            if viewport_child is None:
                continue
            inner_obj = next((c for c in viewport_child if _local_name(c.tag) == "object"), None)
            if inner_obj is None:
                continue
            idx = list(parent).index(child)
            new_child = ET.Element("child", attrib=dict(child.attrib))
            new_child.append(inner_obj)
            parent.remove(child)
            parent.insert(idx, new_child)


def convert_ui(xml_text: str) -> str:
    xml_text = re.sub(r'<\?xml[^?]*\?>', '<?xml version="1.0" encoding="UTF-8"?>', xml_text, count=1)
    root = ET.fromstring(xml_text)
    _process_element(root)
    _unwrap_viewports(root)
    return ET.tostring(root, encoding="unicode")


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} input.ui output.ui", file=sys.stderr)
        return 1
    with open(sys.argv[1], encoding="utf-8") as infile:
        converted = convert_ui(infile.read())
    with open(sys.argv[2], "w", encoding="utf-8") as outfile:
        outfile.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n")
        outfile.write(converted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
