package ai.basic.x1.adapter.port.dao.mybatis.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DatasetSourceMineStatistics {

    private String mineName;

    private Integer datasetAmount;

    private Integer clipAmount;

    private Integer annotatedDataAmount;
}
