package ai.basic.x1.adapter.api.controller;

import ai.basic.x1.adapter.dto.OccGridDTO;
import ai.basic.x1.adapter.dto.request.OccClipExportDTO;
import ai.basic.x1.adapter.dto.request.OccPatchDTO;
import ai.basic.x1.usecase.OccAnnotationUseCase;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.InputStreamResource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.io.IOException;
import java.nio.file.Files;

@RestController
@RequestMapping("/occ/")
public class OccAnnotationController extends BaseController {

    @Autowired
    private OccAnnotationUseCase occAnnotationUseCase;

    @GetMapping("frame")
    public OccGridDTO frame(@RequestParam Long dataId) throws IOException {
        return occAnnotationUseCase.getFrame(dataId, objectMapper);
    }

    @PostMapping("patch")
    public void patch(@RequestBody OccPatchDTO patchDTO) throws IOException {
        occAnnotationUseCase.savePatch(patchDTO, objectMapper);
    }

    @PostMapping("export/clip")
    public ResponseEntity<InputStreamResource> exportClip(@RequestBody OccClipExportDTO exportDTO) throws IOException {
        var exportPath = occAnnotationUseCase.exportClip(exportDTO.getSceneId(), objectMapper);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + exportPath.getFileName() + "\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(new InputStreamResource(Files.newInputStream(exportPath)));
    }
}

