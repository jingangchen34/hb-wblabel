package ai.basic.x1.adapter.dto;

import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class OccGridDTO {

    private OccMetaDTO meta;

    private List<OccVoxelDTO> voxels;

    private Map<Integer, String> colorMap;

    @Data
    public static class OccMetaDTO {
        private List<Integer> gridSize;
        private List<Double> voxelSize;
        private List<Double> origin;
        private String frameId;
    }

    @Data
    public static class OccVoxelDTO {
        private Integer x;
        private Integer y;
        private Integer z;
        private Integer label;
    }
}

