"""XML renderers: FDA eMDR electronic submission exports.

Each MDR record already exists as a human-readable PDF summary; the eMDR
file is the corresponding electronic submission artifact with its own
document identity (EMDR-XXXX), structured like a simplified MedWatch 3500A
export. Serialization is deterministic: fixed element order, two-space
indentation, no timestamps beyond world data.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from gg_synthdata.model import Mdr, World

_UDI_DI_BY_MODEL = {
    "MP-100": "00863125440100",
    "MP-200": "00863125440200",
}


def emdr_id(mdr: Mdr) -> str:
    return f"E{mdr.mdr_id}"


def _sub(parent: ET.Element, tag: str, text: str) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = text
    return element


def render_emdr(world: World, mdr: Mdr, out_dir: Path) -> Path:
    complaint = next(c for c in world.complaints if c.complaint_id == mdr.complaint_id)
    root = ET.Element("emdr")

    header = ET.SubElement(root, "header")
    _sub(header, "report-number", emdr_id(mdr))
    _sub(header, "mdr-record", mdr.mdr_id)
    _sub(header, "date-submitted", mdr.submitted.isoformat())
    _sub(header, "report-type", mdr.event_type.replace("_", " "))

    manufacturer = ET.SubElement(root, "manufacturer")
    _sub(manufacturer, "name", world.company)
    _sub(manufacturer, "registration-site", "Minneapolis, MN, US")

    device = ET.SubElement(root, "device")
    _sub(device, "brand-name", "HALVERN Implantable Infusion Pump")
    _sub(device, "device-model", complaint.model)
    _sub(device, "lot-number", complaint.lot)
    _sub(device, "udi-di", _UDI_DI_BY_MODEL[complaint.model])

    event = ET.SubElement(root, "event")
    _sub(event, "source-complaint", complaint.complaint_id)
    _sub(event, "event-narrative", complaint.description)
    _sub(event, "investigation-summary", complaint.investigation)
    _sub(
        event,
        "reporting-basis",
        "Reportable event under 21 CFR Part 803; submitted per SOP-007.",
    )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{emdr_id(mdr)}.xml"
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


def render_xml_corpus(world: World, corpus_dir: Path) -> list[Path]:
    regulatory_dir = corpus_dir / "10_regulatory"
    return [render_emdr(world, mdr, regulatory_dir) for mdr in world.mdrs]
