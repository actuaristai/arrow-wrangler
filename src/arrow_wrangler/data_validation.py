"""Define models for data validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pandera as pa
from great_tables import GT
from loguru import logger

if TYPE_CHECKING:
    from ibis.expr.types.relations import Table


def validate_table(table: Table, schema: pa.DataFrameSchema) -> None:
    """Check table against a pandera schema.

    Parameters
    ----------
    table : Table
        table to test
    schema : pa.DataFrameSchema
        schema that must be followed by the table
    """
    try:
        schema.validate(table.to_pandas(), lazy=True)
        logger.info('Data validation check ok')

    except pa.errors.SchemaErrors as exc:
        error_msg = exc.__str__()
        error_msg = error_msg.split('Usage Tip')[0]  # to decrease verbosity
        logger.warning(error_msg)


def extract_checks_description(checks: list[pa.Check]) -> list[str]:
    """Return description of list of checks.

    Parameters
    ----------
    checks : list[pa.Check]
        list of pandera checks

    Returns:
    -------
    list[str]
        description of checks as strings
    """
    checks_description = [c.error if c.error is not None else c.name for c in checks]
    return ' ; '.join(checks_description)


def get_schema_description(schema: pa.DataFrameSchema) -> GT:
    """Generate table description from pandera schema.

    Some DataFrameSchema attributes are not described here (e.g. strict, ordered, unique).
    They could be added in the future.

    Parameters
    ----------
    schema : pa.DataFrameSchema
        pandera schema to describe

    Returns:
    -------
    GT
        description of the pandera schema as a great_table
    """
    columns_description = [
        {'column_name': col.name,
         'type': str(col.dtype),
         'coerce': col.coerce,
         'nullable': col.nullable,
         'checks': extract_checks_description(col.checks),
         'description': col.description} for col in schema.columns.values()]

    gt = GT(pd.DataFrame(columns_description)).tab_header(title=schema.name, subtitle=schema.description)
    return gt.tab_source_note(f'Checks on the table level: {extract_checks_description(schema.checks)}')
