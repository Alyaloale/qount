"""Public compatibility exports loaded only when requested."""
from importlib import import_module

_EXPORTS = {
    'BACKUP_SCHEMA_VERSION': ('qount.operations.backups', 'BACKUP_SCHEMA_VERSION'),
    'AUTHORITY_WRITER_SCHEMA_VERSION': ('qount.operations.authority_writer', 'AUTHORITY_WRITER_SCHEMA_VERSION'),
    'BASE_STANDARD_PRODUCTION_CHAIN': ('qount.operations.base_production', 'BASE_STANDARD_PRODUCTION_CHAIN'),
    'BASE_STANDARD_PRODUCTION_MODE': ('qount.operations.base_production', 'BASE_STANDARD_PRODUCTION_MODE'),
    'BASE_STANDARD_PRODUCTION_SCHEMA_VERSION': ('qount.operations.base_production', 'BASE_STANDARD_PRODUCTION_SCHEMA_VERSION'),
    'AuthorityWriterBlocked': ('qount.operations.authority_writer', 'AuthorityWriterBlocked'),
    'AuthorityWriterConfig': ('qount.operations.authority_writer', 'AuthorityWriterConfig'),
    'AuthorityWriterError': ('qount.operations.authority_writer', 'AuthorityWriterError'),
    'AuthorityWriterResult': ('qount.operations.authority_writer', 'AuthorityWriterResult'),
    'authorize_minimal_live_authority_bundle': ('qount.operations.authority_writer', 'authorize_minimal_live_authority_bundle'),
    'BackupError': ('qount.operations.backups', 'BackupError'),
    'BackupRecord': ('qount.operations.backups', 'BackupRecord'),
    'BackupRetentionResult': ('qount.operations.backups', 'BackupRetentionResult'),
    'BaseStandardProductionError': ('qount.operations.base_production', 'BaseStandardProductionError'),
    'CommandResult': ('qount.operations.health_probes', 'CommandResult'),
    'HealthProbeConfig': ('qount.operations.health_probes', 'HealthProbeConfig'),
    'HealthProbeDependencies': ('qount.operations.health_probes', 'HealthProbeDependencies'),
    'HealthProbeError': ('qount.operations.health_probes', 'HealthProbeError'),
    'PUBLISHER_AUTHORIZATION_GRANTED': ('qount.operations.publisher_paths', 'PUBLISHER_AUTHORIZATION_GRANTED'),
    'PUBLISHER_AUTHORIZATION_PENDING': ('qount.operations.publisher_paths', 'PUBLISHER_AUTHORIZATION_PENDING'),
    'PUBLISHER_PATH_AUDIT_SCHEMA_VERSION': ('qount.operations.publisher_paths', 'PUBLISHER_PATH_AUDIT_SCHEMA_VERSION'),
    'RELEASE_PROVENANCE_ARTIFACT_TYPE': ('qount.operations.release_provenance', 'RELEASE_PROVENANCE_ARTIFACT_TYPE'),
    'RELEASE_PROVENANCE_SCHEMA_VERSION': ('qount.operations.release_provenance', 'RELEASE_PROVENANCE_SCHEMA_VERSION'),
    'ReleaseProvenanceError': ('qount.operations.release_provenance', 'ReleaseProvenanceError'),
    'PublisherPathAudit': ('qount.operations.publisher_paths', 'PublisherPathAudit'),
    'PublisherPathAuditError': ('qount.operations.publisher_paths', 'PublisherPathAuditError'),
    'prepare_base_standard_production_store': ('qount.operations.base_production', 'prepare_base_standard_production_store'),
    'RestoreDrillResult': ('qount.operations.backups', 'RestoreDrillResult'),
    'create_dashboard_backup': ('qount.operations.backups', 'create_dashboard_backup'),
    'collect_os_system_health': ('qount.operations.health_probes', 'collect_os_system_health'),
    'prune_dashboard_backups': ('qount.operations.backups', 'prune_dashboard_backups'),
    'read_latest_dashboard_backup': ('qount.operations.backups', 'read_latest_dashboard_backup'),
    'read_base_standard_production_status': ('qount.operations.base_production', 'read_base_standard_production_status'),
    'record_base_standard_production_cycle': ('qount.operations.base_production', 'record_base_standard_production_cycle'),
    'refresh_authority_bundle_from_runtime': ('qount.operations.authority_writer', 'refresh_authority_bundle_from_runtime'),
    'verify_dashboard_restore_drill': ('qount.operations.backups', 'verify_dashboard_restore_drill'),
    'write_order_free_authority_bundle': ('qount.operations.authority_writer', 'write_order_free_authority_bundle'),
    'audit_publisher_paths': ('qount.operations.publisher_paths', 'audit_publisher_paths'),
    'build_release_provenance': ('qount.operations.release_provenance', 'build_release_provenance'),
    'build_release_provenance_verification': ('qount.operations.release_provenance', 'build_release_provenance_verification'),
    'verify_release_provenance': ('qount.operations.release_provenance', 'verify_release_provenance'),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    value = getattr(import_module(module), symbol)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
