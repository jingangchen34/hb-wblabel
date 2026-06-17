SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS `data_scene_attribute`
(
    `id`         bigint(20)   NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
    `dataset_id` bigint(20)   NOT NULL COMMENT 'Dataset id',
    `data_id`    bigint(20)   NOT NULL COMMENT 'Scene data id',
    `category`   varchar(64)  NOT NULL COMMENT 'Scene attribute category',
    `sub_type`   varchar(64)  NOT NULL COMMENT 'Scene attribute subtype',
    `created_at` datetime     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Create time',
    `created_by` bigint(20)            DEFAULT NULL COMMENT 'Creator id',
    `updated_at` datetime     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
    `updated_by` bigint(20)            DEFAULT NULL COMMENT 'Modify person id',
    PRIMARY KEY (`id`) USING BTREE,
    UNIQUE KEY `uk_data_scene_attribute_data_id` (`data_id`) USING BTREE,
    KEY `idx_data_scene_attribute_dataset_category` (`dataset_id`, `category`, `sub_type`) USING BTREE
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4 COMMENT ='Scene attribute for a whole clip';
