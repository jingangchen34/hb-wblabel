package ai.basic.x1.adapter.port.dao.mybatis.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DatasetSourceClassStatistics {

    private String mineName;

    private String className;

    private String color;

    private Integer objectAmount;
}
