ALTER TABLE `model_evaluation_record`
    ADD COLUMN `source_point_dim` int DEFAULT NULL COMMENT 'Raw point-cloud feature dimension',
    ADD COLUMN `model_input_dim` int DEFAULT NULL COMMENT 'Model input feature dimension';
