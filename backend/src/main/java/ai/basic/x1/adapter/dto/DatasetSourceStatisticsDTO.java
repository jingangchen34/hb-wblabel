package ai.basic.x1.adapter.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class DatasetSourceStatisticsDTO {

    private String sourceName;

    private Integer datasetAmount;

    private Integer clipAmount;

    private Integer annotatedDataAmount;

    private List<ClassUnit> classTotals;

    private List<MineUnit> mineUnits;

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class MineUnit {

        private String mineName;

        private Integer datasetAmount;

        private Integer clipAmount;

        private Integer annotatedDataAmount;

        private List<ClassUnit> classUnits;

        private List<AttributeUnit> attributeUnits;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ClassUnit {

        private String className;

        private String color;

        private Integer objectAmount;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AttributeUnit {

        private String category;

        private String subType;

        private Integer clipAmount;
    }
}
