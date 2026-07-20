ALTER TABLE `model_evaluation_record`
    ADD COLUMN `checkpoint_selection_classes` json DEFAULT NULL COMMENT 'Classes whose mean AP selects the best checkpoint';
