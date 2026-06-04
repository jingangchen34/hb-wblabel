package ai.basic.x1.adapter.api.controller;

import ai.basic.x1.adapter.dto.request.OccClipExportDTO;
import ai.basic.x1.adapter.dto.request.PointLabelSaveDTO;
import ai.basic.x1.usecase.PointLabelUseCase;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.nio.file.Files;

@RestController
@RequestMapping("/point-label/")
public class PointLabelController {

    @Autowired
    private PointLabelUseCase pointLabelUseCase;

    @GetMapping("frame")
    public ResponseEntity<ByteArrayResource> frame(@RequestParam Long dataId) throws IOException {
        return ResponseEntity.ok()
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(new ByteArrayResource(pointLabelUseCase.getLabels(dataId)));
    }

    @PostMapping("save")
    public void save(@RequestBody PointLabelSaveDTO saveDTO) throws IOException {
        pointLabelUseCase.saveLabels(saveDTO);
    }

    @PostMapping("modify")
    public void modify(@RequestBody PointLabelSaveDTO saveDTO) throws IOException {
        pointLabelUseCase.saveLabels(saveDTO);
    }

    @PostMapping("export/clip")
    public ResponseEntity<InputStreamResource> exportClip(@RequestBody OccClipExportDTO exportDTO) throws IOException {
        var exportPath = pointLabelUseCase.exportClip(exportDTO.getSceneId());
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + exportPath.getFileName() + "\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(new InputStreamResource(Files.newInputStream(exportPath)));
    }
}
