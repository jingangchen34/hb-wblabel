SET @index_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'data'
      AND index_name = 'idx_data_dataset_active_type_annotation'
);

SET @create_index_sql = IF(
    @index_exists = 0,
    'CREATE INDEX idx_data_dataset_active_type_annotation ON data (dataset_id, is_deleted, type, annotation_status)',
    'SELECT 1'
);

PREPARE create_index_statement FROM @create_index_sql;
EXECUTE create_index_statement;
DEALLOCATE PREPARE create_index_statement;
