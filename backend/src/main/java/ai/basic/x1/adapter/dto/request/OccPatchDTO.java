package ai.basic.x1.adapter.dto.request;

import ai.basic.x1.adapter.dto.OccGridDTO;
import lombok.Data;

import java.util.List;

@Data
public class OccPatchDTO {

    private Long dataId;

    private String frameId;

    private OccGridDTO.OccMetaDTO meta;

    private List<OccEditDTO> edits;

    @Data
    public static class OccEditDTO {
        private Integer x;
        private Integer y;
        private Integer z;
        private Integer from;
        private Integer to;
    }
}

