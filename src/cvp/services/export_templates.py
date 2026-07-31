"""Validation and CRUD for custom CSV export templates."""

from dataclasses import dataclass

from sqlalchemy.orm import Session, selectinload

from cvp.models import ExportTemplate, ExportTemplateColumn
from cvp.services.export_fields import FIELD_REGISTRY

SORT_FIELDS: tuple[str, ...] = ("line_number", "room", "category", "description")


@dataclass
class ColumnSpec:
    field_key: str | None
    header_label: str | None
    static_value: str | None


def validate(name: str, sort_field: str, columns: list[ColumnSpec]) -> None:
    if not name or not name.strip():
        raise ValueError("Template name is required.")
    if sort_field not in SORT_FIELDS:
        raise ValueError(f"Invalid sort field: {sort_field!r}")
    if not columns:
        raise ValueError("A template needs at least one column.")
    for i, col in enumerate(columns):
        is_field = col.field_key is not None
        is_static = col.static_value is not None
        if is_field == is_static:
            raise ValueError(f"Column {i}: set exactly one of field_key / static_value.")
        if is_field and col.field_key not in FIELD_REGISTRY:
            raise ValueError(f"Column {i}: unknown field {col.field_key!r}.")
        if is_static and not (col.header_label and col.header_label.strip()):
            raise ValueError(f"Column {i}: static columns require a header label.")


def list_templates(db: Session, group_id: str) -> list[ExportTemplate]:
    return (
        db.query(ExportTemplate)
        .options(selectinload(ExportTemplate.columns))
        .filter(ExportTemplate.group_id == group_id)
        .order_by(ExportTemplate.name)
        .all()
    )


def get_template(db: Session, template_id: str, group_id: str) -> ExportTemplate | None:
    return (
        db.query(ExportTemplate)
        .options(selectinload(ExportTemplate.columns))
        .filter(ExportTemplate.id == template_id, ExportTemplate.group_id == group_id)
        .first()
    )


def _apply_columns(template: ExportTemplate, columns: list[ColumnSpec]) -> None:
    template.columns.clear()  # orphan-delete removes old rows
    for pos, spec in enumerate(columns):
        template.columns.append(
            ExportTemplateColumn(
                position=pos,
                field_key=spec.field_key,
                header_label=(spec.header_label or None),
                static_value=spec.static_value,
            )
        )


def create_template(
    db: Session,
    *,
    group_id: str,
    created_by_id: str | None,
    name: str,
    description: str,
    include_needs_review: bool,
    include_excluded: bool,
    sort_field: str,
    columns: list[ColumnSpec],
) -> ExportTemplate:
    validate(name, sort_field, columns)
    template = ExportTemplate(
        group_id=group_id,
        created_by_id=created_by_id,
        name=name.strip(),
        description=description or "",
        include_needs_review=include_needs_review,
        include_excluded=include_excluded,
        sort_field=sort_field,
    )
    _apply_columns(template, columns)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(
    db: Session,
    template: ExportTemplate,
    *,
    name: str,
    description: str,
    include_needs_review: bool,
    include_excluded: bool,
    sort_field: str,
    columns: list[ColumnSpec],
) -> ExportTemplate:
    validate(name, sort_field, columns)
    template.name = name.strip()
    template.description = description or ""
    template.include_needs_review = include_needs_review
    template.include_excluded = include_excluded
    template.sort_field = sort_field
    _apply_columns(template, columns)
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, template: ExportTemplate) -> None:
    db.delete(template)
    db.commit()


def xactimate_default_columns() -> list[ColumnSpec]:
    """Column layout mirroring the fixed Xactimate CSV, as a starting point."""
    keys = [
        "line_number",
        "description",
        "quantity",
        "unit",
        "unit_price",
        "rcv_total",
        "depreciation",
        "acv_total",
        "category",
        "room",
        "age",
        "condition",
        "source_notes",
    ]
    return [ColumnSpec(field_key=k, header_label=None, static_value=None) for k in keys]
