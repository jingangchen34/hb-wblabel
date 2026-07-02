package ai.basic.x1.adapter.port.dao.mybatis.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DatasetSourceAttributeStatistics {

    private String mineName;

    private String category;

    private String subType;

    private Integer clipAmount;
}
