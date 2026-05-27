"""
pipe-recon — enterprise pipeline reconciliation driven by mapping documents.

Quick start:
    from reconpilot import load_mapping, connect_dsn, reconcile_from_mapping

    doc = load_mapping("mapping/CRM_Field_Mapping.csv")
    src = connect_dsn("postgresql://user:pass@source/crm", name="CRM")
    tgt = connect_dsn("postgresql://user:pass@target/dw",  name="DW")

    result = reconcile_from_mapping(
        doc, src, tgt,
        source_table="CUSTOMER",
        direction="INBOUND",
        pipeline_name="CRM_Customer_Load",
        run_filter="load_date = CURRENT_DATE",
    )
    result.print()
"""

from reconpilot.mapping import load_mapping, create_sample_mapping, MappingDocument, FieldMapping
from reconpilot.connection import Connection, connect_dsn, connect_from_config
from reconpilot.reconciler import reconcile_from_mapping, RunReconcileReport, FieldResult

__version__ = "0.1.0"
__all__ = [
    "load_mapping",
    "create_sample_mapping",
    "MappingDocument",
    "FieldMapping",
    "Connection",
    "connect_dsn",
    "connect_from_config",
    "reconcile_from_mapping",
    "RunReconcileReport",
    "FieldResult",
]
